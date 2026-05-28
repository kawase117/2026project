from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .stratifiers import default_evaluators


@dataclass
class KpiConfig:
    catastrophic_threshold: float = 15000.0


@dataclass
class KpiRow:
    n_pairs: int
    hit_at_2_rate: float
    loss_mean: float
    loss_p50: float
    loss_p90: float
    loss_p95: float
    rank2_rescue_on_miss1: float
    rank3_rescue_on_miss12: float
    critical_miss_rate: float
    catastrophic_rate: float
    catastrophic_on_critical_rate: float


def _safe_mean(series: pd.Series) -> float:
    if len(series) == 0:
        return float("nan")
    return float(pd.to_numeric(series, errors="coerce").mean())


def _safe_quantile(series: pd.Series, q: float) -> float:
    ser = pd.to_numeric(series, errors="coerce").dropna()
    if len(ser) == 0:
        return float("nan")
    return float(ser.quantile(q))


def _compute_kpi_row(df: pd.DataFrame, cfg: KpiConfig) -> KpiRow:
    miss1 = df[df["top1_match"] == 0]
    miss12 = df[(df["top1_match"] == 0) & (df["top2_match"] == 0)]
    critical = df[df["loss_scenario"] == "critical_miss"]
    loss = pd.to_numeric(df["loss_value"], errors="coerce")
    catastrophic = loss >= float(cfg.catastrophic_threshold)
    catastrophic_on_critical = (
        pd.to_numeric(critical["loss_value"], errors="coerce") >= float(cfg.catastrophic_threshold)
    )
    return KpiRow(
        n_pairs=int(len(df)),
        hit_at_2_rate=_safe_mean(df["hit_at_2"]),
        loss_mean=_safe_mean(df["loss_value"]),
        loss_p50=_safe_quantile(df["loss_value"], 0.50),
        loss_p90=_safe_quantile(df["loss_value"], 0.90),
        loss_p95=_safe_quantile(df["loss_value"], 0.95),
        rank2_rescue_on_miss1=float((miss1["top2_match"] == 1).mean()) if len(miss1) > 0 else float("nan"),
        rank3_rescue_on_miss12=float((miss12["top3_match"] == 1).mean()) if len(miss12) > 0 else float("nan"),
        critical_miss_rate=float((df["loss_scenario"] == "critical_miss").mean()) if len(df) > 0 else float("nan"),
        catastrophic_rate=float(catastrophic.mean()) if len(df) > 0 else float("nan"),
        catastrophic_on_critical_rate=float(catastrophic_on_critical.mean()) if len(critical) > 0 else float("nan"),
    )


def _delta(cur: float, base: float, *, higher_is_better: bool) -> dict[str, Any]:
    if not np.isfinite(cur) or not np.isfinite(base):
        return {"current": cur, "baseline": base, "delta": float("nan"), "direction": "unknown"}
    d = float(cur - base)
    improved = d > 0 if higher_is_better else d < 0
    worsened = d < 0 if higher_is_better else d > 0
    direction = "improved" if improved else ("worsened" if worsened else "flat")
    return {"current": cur, "baseline": base, "delta": d, "direction": direction}


def build_kpi_summary(
    *,
    current_loss_df: pd.DataFrame,
    baseline_loss_df: pd.DataFrame | None = None,
    config: KpiConfig | None = None,
) -> dict[str, Any]:
    cfg = config or KpiConfig()
    current_overall = asdict(_compute_kpi_row(current_loss_df, cfg))

    by_expert_rows: list[dict[str, Any]] = []
    for expert, sub in current_loss_df.groupby("expert", sort=True):
        row = asdict(_compute_kpi_row(sub, cfg))
        row["expert"] = str(expert)
        by_expert_rows.append(row)

    by_condition_rows: list[dict[str, Any]] = []
    for evaluator in default_evaluators():
        for difficulty, sub in evaluator.stratify(current_loss_df).items():
            row = asdict(_compute_kpi_row(sub, cfg))
            row["condition"] = evaluator.condition_name
            row["difficulty"] = difficulty
            by_condition_rows.append(row)

    out: dict[str, Any] = {
        "config": asdict(cfg),
        "current": {
            "overall": current_overall,
            "by_expert": by_expert_rows,
            "by_condition": by_condition_rows,
        },
    }

    if baseline_loss_df is not None and not baseline_loss_df.empty:
        baseline_overall = asdict(_compute_kpi_row(baseline_loss_df, cfg))
        out["baseline"] = {"overall": baseline_overall}
        out["overall_delta"] = {
            "hit_at_2_rate": _delta(
                current_overall["hit_at_2_rate"],
                baseline_overall["hit_at_2_rate"],
                higher_is_better=True,
            ),
            "loss_mean": _delta(
                current_overall["loss_mean"],
                baseline_overall["loss_mean"],
                higher_is_better=False,
            ),
            "rank2_rescue_on_miss1": _delta(
                current_overall["rank2_rescue_on_miss1"],
                baseline_overall["rank2_rescue_on_miss1"],
                higher_is_better=True,
            ),
            "critical_miss_rate": _delta(
                current_overall["critical_miss_rate"],
                baseline_overall["critical_miss_rate"],
                higher_is_better=False,
            ),
            "catastrophic_rate": _delta(
                current_overall["catastrophic_rate"],
                baseline_overall["catastrophic_rate"],
                higher_is_better=False,
            ),
        }
    return out


def build_kpi_summary_table(kpi_summary: dict[str, Any]) -> pd.DataFrame:
    cur = kpi_summary["current"]["overall"]
    rows = [{"scope": "current_overall", **cur}]
    base = kpi_summary.get("baseline", {}).get("overall")
    if base:
        rows.append({"scope": "baseline_overall", **base})
    deltas = kpi_summary.get("overall_delta")
    if deltas:
        flat = {"scope": "overall_delta"}
        for metric, payload in deltas.items():
            flat[f"{metric}_delta"] = payload.get("delta")
            flat[f"{metric}_direction"] = payload.get("direction")
        rows.append(flat)
    return pd.DataFrame(rows)


def generate_kpi_decision_memo(kpi_summary: dict[str, Any]) -> str:
    cur = kpi_summary["current"]["overall"]
    lines: list[str] = []
    lines.append("# KPI Decision Memo")
    lines.append("")
    lines.append("## Current KPI Snapshot")
    lines.append(f"- n_pairs: {int(cur['n_pairs'])}")
    lines.append(f"- hit_at_2_rate: {float(cur['hit_at_2_rate']):.4f}")
    lines.append(f"- loss_mean: {float(cur['loss_mean']):.2f}")
    lines.append(f"- loss_p50 / p90 / p95: {float(cur['loss_p50']):.2f} / {float(cur['loss_p90']):.2f} / {float(cur['loss_p95']):.2f}")
    lines.append(f"- rank2_rescue_on_miss1: {float(cur['rank2_rescue_on_miss1']):.4f}")
    lines.append(f"- critical_miss_rate: {float(cur['critical_miss_rate']):.4f}")
    lines.append(f"- catastrophic_rate: {float(cur['catastrophic_rate']):.4f}")

    delta = kpi_summary.get("overall_delta")
    if delta:
        lines.append("")
        lines.append("## Baseline Delta")
        for metric in [
            "hit_at_2_rate",
            "loss_mean",
            "rank2_rescue_on_miss1",
            "critical_miss_rate",
            "catastrophic_rate",
        ]:
            d = delta.get(metric, {})
            lines.append(
                f"- {metric}: current={d.get('current', float('nan')):.4f}, "
                f"baseline={d.get('baseline', float('nan')):.4f}, "
                f"delta={d.get('delta', float('nan')):+.4f}, "
                f"direction={d.get('direction', 'unknown')}"
            )
        lines.append("")
        lines.append("## Decision")
        worsened = {
            "loss_mean",
            "critical_miss_rate",
            "catastrophic_rate",
        }
        if any(delta.get(m, {}).get("direction") == "worsened" for m in worsened):
            lines.append("reject_or_rework")
        elif any(delta.get(m, {}).get("direction") == "improved" for m in ["hit_at_2_rate", "rank2_rescue_on_miss1"]):
            lines.append("adopt_or_pilot")
        else:
            lines.append("pilot_with_monitoring")
    return "\n".join(lines).strip() + "\n"
