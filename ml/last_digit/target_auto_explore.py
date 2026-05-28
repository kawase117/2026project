from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.tail_ltr_split_rule_wf import aggregate_mode, build_base_rows, resolve_db_path


def _run(cmd: list[str], *, cwd: Path, timeout_sec: int) -> None:
    print("RUN:", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=str(cwd), timeout=timeout_sec, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(cmd)}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_actual_worst_map(*, db_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    raw = build_base_rows(db_path=db_path, a_weight=0.4, non_a_weight=1.3)
    agg = aggregate_mode(raw, mode="floor_atype4").copy()
    agg["date"] = pd.to_datetime(agg["date"]).dt.strftime("%Y-%m-%d")
    agg["group_key"] = agg["group_key"].astype(str)
    agg["last_digit"] = agg["last_digit"].astype(str)
    agg["total_diff_coins"] = pd.to_numeric(agg["total_diff_coins"], errors="coerce").fillna(0.0)

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for (dt, ex), g in agg.groupby(["date", "group_key"], sort=False):
        w = g.sort_values(["total_diff_coins", "last_digit"], ascending=[True, True]).reset_index(drop=True)
        if w.empty:
            continue
        worst1 = str(w.iloc[0]["last_digit"])
        worst2_set = set(w.head(2)["last_digit"].astype(str).tolist())
        worst3_set = set(w.head(3)["last_digit"].astype(str).tolist())
        out[(str(dt), str(ex))] = {
            "worst1": worst1,
            "worst2_set": worst2_set,
            "worst3_set": worst3_set,
        }
    return out


def _evaluate_worst(topk_csv: Path, *, db_path: Path) -> dict[str, Any]:
    df = pd.read_csv(topk_csv, encoding="utf-8-sig")
    if df.empty:
        return {"n": 0}
    need = {"date", "expert", "top1_tail", "top2_tail", "top1_actual_raw_diff", "top2_actual_raw_diff"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in worst topk CSV: {sorted(missing)}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["expert"] = df["expert"].astype(str)
    df["top1_tail"] = df["top1_tail"].astype(str)
    df["top2_tail"] = df["top2_tail"].astype(str)
    df["top1_actual_raw_diff"] = pd.to_numeric(df["top1_actual_raw_diff"], errors="coerce")
    df["top2_actual_raw_diff"] = pd.to_numeric(df["top2_actual_raw_diff"], errors="coerce")

    worst_map = _build_actual_worst_map(db_path=db_path)
    rows: list[dict[str, Any]] = []
    for rec in df.to_dict(orient="records"):
        key = (rec["date"], rec["expert"])
        gt = worst_map.get(key)
        if gt is None:
            continue
        rows.append(
            {
                "date": rec["date"],
                "expert": rec["expert"],
                "pred1": rec["top1_tail"],
                "pred2": rec["top2_tail"],
                "pred1_diff": float(rec["top1_actual_raw_diff"]) if pd.notna(rec["top1_actual_raw_diff"]) else np.nan,
                "pred2_diff": float(rec["top2_actual_raw_diff"]) if pd.notna(rec["top2_actual_raw_diff"]) else np.nan,
                "worst1_hit": int(rec["top1_tail"] == gt["worst1"]),
                "worst2_cover": int((rec["top1_tail"] in gt["worst2_set"]) or (rec["top2_tail"] in gt["worst2_set"])),
                "worst3_cover": int((rec["top1_tail"] in gt["worst3_set"]) or (rec["top2_tail"] in gt["worst3_set"])),
                "pred1_negative": int(pd.notna(rec["top1_actual_raw_diff"]) and float(rec["top1_actual_raw_diff"]) < 0.0),
                "pred1_hard_negative": int(pd.notna(rec["top1_actual_raw_diff"]) and float(rec["top1_actual_raw_diff"]) <= -5000.0),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return {"n": 0}
    return {
        "n": int(len(out)),
        "worst1_hit_rate": float(out["worst1_hit"].mean()),
        "worst2_cover_rate": float(out["worst2_cover"].mean()),
        "worst3_cover_rate": float(out["worst3_cover"].mean()),
        "pred1_negative_rate": float(out["pred1_negative"].mean()),
        "pred1_hard_negative_rate": float(out["pred1_hard_negative"].mean()),
        "pred1_diff_median": float(pd.to_numeric(out["pred1_diff"], errors="coerce").median()),
        "pred1_diff_mean": float(pd.to_numeric(out["pred1_diff"], errors="coerce").mean()),
    }


def _extract_summary(payload: dict[str, Any], *, target: str) -> dict[str, Any]:
    base = {
        "target_label": target,
        "source_latest_date": payload.get("source_latest_date", ""),
        "target_date": payload.get("target_date", ""),
        "test_period_enabled": bool(payload.get("test_period_report_enabled", False)),
        "ceiling_status": payload.get("ceiling_effect_report_status", ""),
    }
    outputs = payload.get("ceiling_effect_outputs") or {}
    if isinstance(outputs, dict):
        base["ceiling_dir"] = str(outputs.get("condition_significance", "")).replace("\\condition_significance.csv", "")
    else:
        base["ceiling_dir"] = ""
    return base


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Auto target exploration runner for T1/T2/Worst")
    p.add_argument("--output-root", default="", help="Output root dir. Default: timestamped under exploratory/kamata7_only/")
    p.add_argument("--db-path", default="", help="Optional DB path override")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--model", default="xgb_ranker_ndcg")
    p.add_argument("--timeout-sec", type=int, default=7200)
    p.add_argument("--gpu-backend", choices=["cuda", "gpu_hist"], default="cuda")
    args = p.parse_args(argv)

    cwd = Path.cwd()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = (
        Path(args.output_root)
        if str(args.output_root).strip()
        else Path("ml/last_digit/exploratory/kamata7_only") / f"target_auto_explore_{ts}"
    )
    out_root.mkdir(parents=True, exist_ok=True)

    base_cmd = [
        sys.executable,
        "-m",
        "ml.last_digit.tail_ltr_split_rule_nextday_gpu",
        "--model",
        str(args.model),
        "--gpu-backend",
        str(args.gpu_backend),
        "--seed",
        str(int(args.seed)),
        "--enable-test-period-report",
        "--enable-ceiling-effect-report",
    ]
    if str(args.db_path).strip():
        base_cmd.extend(["--db-path", str(args.db_path)])
    else:
        base_cmd.extend(["--db-path", str(resolve_db_path())])

    exp_specs: list[tuple[str, str]] = [
        ("top2_refit", "is_top_2"),
        ("t1_rank1", "is_rank_1"),
        ("t2_top3", "is_top_3"),
        ("worst1", "is_worst_1"),
    ]

    payload_paths: dict[str, Path] = {}
    top2_topk_path: Path | None = None

    for name, target in exp_specs:
        out_prefix = out_root / name / "run"
        out_prefix.parent.mkdir(parents=True, exist_ok=True)
        cmd = list(base_cmd)
        cmd.extend(["--target-label", target, "--output-prefix", str(out_prefix)])
        if name in {"t1_rank1", "t2_top3"} and top2_topk_path is not None:
            cmd.extend(["--ceiling-baseline-topk", str(top2_topk_path)])
        _run(cmd, cwd=cwd, timeout_sec=int(args.timeout_sec))
        payload_path = out_prefix.with_name(out_prefix.name + f"_{args.model}.json")
        if not payload_path.exists():
            raise FileNotFoundError(f"Missing payload JSON: {payload_path}")
        payload_paths[name] = payload_path
        if name == "top2_refit":
            top2_candidate = out_prefix.with_name(out_prefix.name + f"_{args.model}_testperiod_topk.csv")
            if top2_candidate.exists():
                top2_topk_path = top2_candidate

    rows: list[dict[str, Any]] = []
    for name, target in exp_specs:
        payload = _load_json(payload_paths[name])
        rec = {"experiment": name, **_extract_summary(payload, target=target)}
        rows.append(rec)

    summary = pd.DataFrame(rows)
    summary_csv = out_root / "summary.csv"
    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")

    worst_eval = {}
    worst_topk = out_root / "worst1" / f"run_{args.model}_testperiod_topk.csv"
    if worst_topk.exists():
        worst_eval = _evaluate_worst(worst_topk, db_path=Path(args.db_path) if str(args.db_path).strip() else resolve_db_path())

    report = {
        "output_root": str(out_root),
        "top2_baseline_topk": str(top2_topk_path) if top2_topk_path else "",
        "experiments": rows,
        "worst_eval": worst_eval,
    }
    report_json = out_root / "report.json"
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report_md = out_root / "report.md"
    md_lines = [
        "# Target Auto Explore Report",
        "",
        f"- output_root: `{out_root}`",
        f"- top2_baseline_topk: `{top2_topk_path}`",
        "",
        "## Summary",
        "",
        "```text",
        summary.to_string(index=False),
        "```",
        "",
    ]
    if worst_eval:
        md_lines.extend(
            [
                "## Worst1 Eval",
                "",
                *(f"- {k}: {v}" for k, v in worst_eval.items()),
                "",
            ]
        )
    report_md.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"summary_csv: {summary_csv}")
    print(f"report_json: {report_json}")
    print(f"report_md: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
