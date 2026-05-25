from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_MAJOR_METRICS = ("hit_at_2", "loss_value", "rank2_rescue_on_miss1")
_HIGHER_IS_BETTER = {"hit_at_2", "rank2_rescue_on_miss1"}
_LOWER_IS_BETTER = {"loss_value"}


def _is_sig(row: pd.Series) -> bool:
    return bool(pd.to_numeric(row.get("sig_bh_0_05"), errors="coerce") == 1)


def _is_improvement(row: pd.Series) -> bool:
    metric = str(row.get("metric"))
    delta = float(pd.to_numeric(row.get("delta_mean"), errors="coerce"))
    if metric in _HIGHER_IS_BETTER:
        return delta > 0
    if metric in _LOWER_IS_BETTER:
        return delta < 0
    return False


def _is_worsening(row: pd.Series) -> bool:
    metric = str(row.get("metric"))
    delta = float(pd.to_numeric(row.get("delta_mean"), errors="coerce"))
    if metric in _HIGHER_IS_BETTER:
        return delta < 0
    if metric in _LOWER_IS_BETTER:
        return delta > 0
    return False


def _decision_label(
    *,
    sig_improve_count: int,
    major_worsen_count: int,
    low_support_count: int,
) -> str:
    if major_worsen_count > 0:
        return "非採用"
    if sig_improve_count > 0 and low_support_count == 0:
        return "採用推奨"
    if sig_improve_count > 0:
        return "条件付き採用"
    return "条件付き採用"


def _pick_largest(sub: pd.DataFrame, *, improvement: bool) -> dict[str, Any] | None:
    if sub.empty:
        return None
    filt = sub[sub.apply(_is_improvement if improvement else _is_worsening, axis=1)].copy()
    filt = filt[filt.apply(_is_sig, axis=1)].copy()
    if filt.empty:
        return None
    filt["abs_d"] = pd.to_numeric(filt["cohens_d"], errors="coerce").abs()
    rec = filt.sort_values(["abs_d", "p_value_adj_bh"], ascending=[False, True]).iloc[0]
    return rec.to_dict()


def _metric_section(sig_df: pd.DataFrame, metric: str) -> str:
    sub = sig_df[sig_df["metric"] == metric].copy()
    if sub.empty:
        return f"### {metric}\nデータなし\n"
    imp = sub[sub.apply(_is_improvement, axis=1) & sub.apply(_is_sig, axis=1)]
    wrs = sub[sub.apply(_is_worsening, axis=1) & sub.apply(_is_sig, axis=1)]
    status = "不変"
    if len(wrs) > 0:
        status = "悪化"
    elif len(imp) > 0:
        status = "改善"

    rep = sub.sort_values("p_value_adj_bh", ascending=True).iloc[0]
    ci_low = float(pd.to_numeric(rep["ci_low"], errors="coerce"))
    ci_high = float(pd.to_numeric(rep["ci_high"], errors="coerce"))
    delta = float(pd.to_numeric(rep["delta_mean"], errors="coerce"))
    p_bh = float(pd.to_numeric(rep["p_value_adj_bh"], errors="coerce"))
    d = float(pd.to_numeric(rep["cohens_d"], errors="coerce"))
    d_label = str(rep.get("cohens_d_label", "n/a"))
    cond = f"{rep['condition']}/{rep['difficulty']}"
    return (
        f"### {metric}\n"
        f"代表条件: `{cond}`\n"
        f"Δ mean: {delta:+.4f}, CI=[{ci_low:+.4f}, {ci_high:+.4f}], p_BH={p_bh:.4g}, d={d:.3f} ({d_label})\n"
        f"有意改善: {len(imp)}件, 有意悪化: {len(wrs)}件\n"
        f"→ {status}\n"
    )


def generate_decision_memo(sig_df: pd.DataFrame, diagnostics: dict[str, Any] | None = None) -> str:
    diagnostics = diagnostics or {}
    if sig_df.empty:
        return "# 評価サマリ\n\n有意差データがありません（baseline 未設定または比較対象なし）。\n"

    sig_df = sig_df.copy()
    sig_imp = sig_df[sig_df.apply(_is_improvement, axis=1) & sig_df.apply(_is_sig, axis=1)]
    sig_wrs = sig_df[sig_df.apply(_is_worsening, axis=1) & sig_df.apply(_is_sig, axis=1)]
    major = sig_df[sig_df["metric"].isin(_MAJOR_METRICS)].copy()
    major_wrs = major[major.apply(_is_worsening, axis=1) & major.apply(_is_sig, axis=1)]
    low_support = sig_df[
        (pd.to_numeric(sig_df["n_current"], errors="coerce") < 10)
        | (pd.to_numeric(sig_df["n_baseline"], errors="coerce") < 10)
    ]

    decision = _decision_label(
        sig_improve_count=len(sig_imp),
        major_worsen_count=len(major_wrs),
        low_support_count=len(low_support),
    )

    imp_top = _pick_largest(sig_df, improvement=True)
    wrs_top = _pick_largest(sig_df, improvement=False)
    mean_d = float(pd.to_numeric(sig_df["cohens_d"], errors="coerce").mean())

    lines: list[str] = []
    lines.append("# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1")
    lines.append("## 結論")
    lines.append(f"{decision}")
    lines.append("")
    lines.append("## 全体スナップショット")
    lines.append(f"- BH有意改善: {len(sig_imp)}件")
    lines.append(f"- BH有意悪化: {len(sig_wrs)}件")
    lines.append(f"- 平均Cohen's d: {mean_d:.3f}")
    if imp_top is not None:
        lines.append(
            "- 最大改善: "
            f"{imp_top['condition']}/{imp_top['difficulty']} ({imp_top['metric']}, d={float(imp_top['cohens_d']):.3f})"
        )
    else:
        lines.append("- 最大改善: なし")
    if wrs_top is not None:
        lines.append(
            "- 最大悪化: "
            f"{wrs_top['condition']}/{wrs_top['difficulty']} ({wrs_top['metric']}, d={float(wrs_top['cohens_d']):.3f})"
        )
    else:
        lines.append("- 最大悪化: なし")
    cur = diagnostics.get("current", {})
    base = diagnostics.get("baseline", {})
    if cur:
        lines.append(f"- current pairs: {cur.get('unique_pairs', 'n/a')} (days={cur.get('n_days', 'n/a')})")
    if base:
        lines.append(f"- baseline overlap: {base.get('overlap_pairs', 'n/a')} pairs")
    lines.append("")
    lines.append("## メトリクス別評価")
    lines.append(_metric_section(sig_df, "hit_at_2"))
    lines.append(_metric_section(sig_df, "loss_value"))
    lines.append(_metric_section(sig_df, "rank2_rescue_on_miss1"))
    lines.append("## リスク評価")
    lines.append(f"- 悪化条件の有無: {'あり' if len(sig_wrs) > 0 else 'なし'}")
    lines.append(f"- サンプルサイズ警告（n<10）: {'あり' if len(low_support) > 0 else 'なし'} ({len(low_support)}件)")
    pilot = "推奨" if (len(low_support) > 0 or len(sig_wrs) > 0) else "不要"
    lines.append(f"- パイロット検証推奨: {pilot}")
    lines.append("")
    lines.append("## 補足")
    if imp_top is not None:
        lines.append(f"- 最も有効な条件: {imp_top['condition']}/{imp_top['difficulty']} ({imp_top['metric']})")
    if wrs_top is not None:
        lines.append(f"- 注意すべき条件: {wrs_top['condition']}/{wrs_top['difficulty']} ({wrs_top['metric']})")
    target = major[major.apply(_is_improvement, axis=1) & major.apply(_is_sig, axis=1)]
    if not target.empty:
        top_target = target.assign(abs_d=pd.to_numeric(target["cohens_d"], errors="coerce").abs()).sort_values(
            "abs_d", ascending=False
        ).iloc[0]
        lines.append(f"- ターゲット改善層: {top_target['condition']}/{top_target['difficulty']}")
    return "\n".join(lines).strip() + "\n"
