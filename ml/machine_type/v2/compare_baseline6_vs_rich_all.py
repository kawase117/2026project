from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FOCUS_FEATURES = [
    "days_since_last_rank1",
    "rank_trend_1m_vs_2m",
    "ewm_rank_momentum_7v30",
    "same_weekday_rank1_rate",
    "days_since_last_top3",
    "rank_pct_trend_7vs28",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _combined_metrics(payload: dict[str, Any]) -> dict[str, float]:
    c = payload.get("target_is_top3", {}).get("combined", {})
    return {
        "combined_hit_at_1": float(c.get("hit_at_1", np.nan)),
        "combined_hit_at_3": float(c.get("hit_at_3", np.nan)),
        "combined_auc": float(c.get("auc", np.nan)),
        "combined_lift_at_1": float(c.get("lift_at_1", np.nan)),
    }


def _segment_metrics(payload: dict[str, Any]) -> dict[str, float]:
    t = payload.get("target_is_top3", {})
    return {
        "hit_at_1": float(t.get("hit_at_1", np.nan)),
        "auc": float(t.get("auc", np.nan)),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compare machine_type v2 baseline6 vs rich_all outputs.")
    p.add_argument("--baseline-dir", default="ml/machine_type/v2/output_ltr_90d")
    p.add_argument("--rich-dir", default="ml/machine_type/v2/output_ltr_rich_90d")
    p.add_argument("--output-report", default="ml/machine_type/v2/comparison_baseline6_vs_rich_all.txt")
    return p


def main() -> int:
    args = build_parser().parse_args()
    base_dir = Path(args.baseline_dir)
    rich_dir = Path(args.rich_dir)

    base_comb = _load_json(base_dir / "layer1_combined_result.json")
    rich_comb = _load_json(rich_dir / "layer1_combined_result.json")
    base_2f = _load_json(base_dir / "layer1_2F_result.json")
    base_3f = _load_json(base_dir / "layer1_3F_result.json")
    rich_2f = _load_json(rich_dir / "layer1_2F_result.json")
    rich_3f = _load_json(rich_dir / "layer1_3F_result.json")

    bm = _combined_metrics(base_comb)
    rm = _combined_metrics(rich_comb)
    b2 = _segment_metrics(base_2f)
    b3 = _segment_metrics(base_3f)
    r2 = _segment_metrics(rich_2f)
    r3 = _segment_metrics(rich_3f)

    rows = [
        ("combined hit@1", bm["combined_hit_at_1"], rm["combined_hit_at_1"]),
        ("combined hit@3", bm["combined_hit_at_3"], rm["combined_hit_at_3"]),
        ("combined AUC", bm["combined_auc"], rm["combined_auc"]),
        ("combined lift@1", bm["combined_lift_at_1"], rm["combined_lift_at_1"]),
        ("2F hit@1", b2["hit_at_1"], r2["hit_at_1"]),
        ("2F AUC", b2["auc"], r2["auc"]),
        ("3F hit@1", b3["hit_at_1"], r3["hit_at_1"]),
        ("3F AUC", b3["auc"], r3["auc"]),
    ]

    lines: list[str] = []
    lines.append("=== 90日評価 baseline6 vs rich_all 比較 ===")
    lines.append(f"{'指標':<24} {'baseline6':>10} {'rich_all':>10} {'差分':>10}")
    lines.append("-" * 58)
    for name, b, r in rows:
        lines.append(f"{name:<24} {b:>10.4f} {r:>10.4f} {r-b:>10.4f}")

    fi = pd.read_csv(rich_dir / "feature_importance_per_segment.csv", encoding="utf-8-sig")
    lines.append("")
    lines.append("=== rich_all Feature Importance Top15 (segment別) ===")

    rank_summary: dict[str, dict[str, int | None]] = {}
    for seg in sorted(fi["segment"].dropna().unique().tolist()):
        seg_df = fi[fi["segment"] == seg].copy().sort_values("importance_mean", ascending=False).reset_index(drop=True)
        lines.append("")
        lines.append(f"[{seg}]")
        for i, (_, r) in enumerate(seg_df.head(15).iterrows(), start=1):
            lines.append(f"{i:>2}. {r['feature']} ({float(r['importance_mean']):.6f})")

        rank_summary[seg] = {}
        for f in FOCUS_FEATURES:
            idx = seg_df.index[seg_df["feature"] == f]
            rank_summary[seg][f] = int(idx[0]) + 1 if len(idx) > 0 else None

    lines.append("")
    lines.append("=== 指定特徴量のランク ===")
    for seg, ranks in rank_summary.items():
        lines.append("")
        lines.append(f"[{seg}]")
        for f in FOCUS_FEATURES:
            rk = ranks[f]
            lines.append(f"- {f}: {'圏外(未出現)' if rk is None else str(rk) + '位'}")

    auc_delta = rm["combined_auc"] - bm["combined_auc"]
    if auc_delta >= 0.02:
        auc_judge = "特徴量追加が有効。rich_all を採用する。"
    elif auc_delta >= 0.01:
        auc_judge = "微改善。重要特徴量を絞ったサブセット再評価が有効。"
    else:
        auc_judge = "改善小/低下。6特徴量で十分、ターゲット再定義検討。"

    ds_ranks = [ranks.get("days_since_last_rank1") for ranks in rank_summary.values()]
    ds_ranks = [x for x in ds_ranks if x is not None]
    if not ds_ranks:
        ds_judge = "days_since_last_rank1 は圏外。サイクル仮説は不採用寄り。"
    elif min(ds_ranks) <= 10:
        ds_judge = f"days_since_last_rank1 は上位10位以内（最良 {min(ds_ranks)}位）。サイクル仮説は有望。"
    else:
        ds_judge = f"days_since_last_rank1 は上位10位外（最良 {min(ds_ranks)}位）。サイクル仮説は弱い。"

    lines.append("")
    lines.append("=== 判定 ===")
    lines.append(f"AUC差分: {auc_delta:.4f} -> {auc_judge}")
    lines.append(ds_judge)

    report = "\n".join(lines) + "\n"
    out_path = Path(args.output_report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
