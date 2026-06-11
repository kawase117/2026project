from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

OUTPUT_DIR = Path("data/mitoya_position_ablation")
CONDITIONS: list[tuple[str, list[str]]] = [
    ("without_position", []),
    ("with_position", ["--use-position-features"]),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mitoya position-feature ablation runner")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--db-path", default="", help="Forwarded to tail_ltr_mitoya_wf.py")
    parser.add_argument("--db-glob", default="縺ｿ縺ｨ繧・､ｧ譽ｮ逕ｺ蠎・db", help="Forwarded to tail_ltr_mitoya_wf.py")
    parser.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--warmup-days", type=int, default=56)
    parser.add_argument("--max-blocks", type=int, default=0)
    parser.add_argument("--modes", default="atype3")
    return parser


def _run_walk_forward(args: argparse.Namespace, condition_name: str, extra_args: list[str]) -> dict:
    output_dir = Path(args.output_dir)
    condition_dir = output_dir / condition_name
    condition_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = condition_dir / "tail_ltr_mitoya_wf"
    out_json = condition_dir / f"{condition_name}.json"
    cmd = [
        sys.executable,
        "-m",
        "ml.last_digit.tail_ltr_mitoya_wf",
        "--output-prefix",
        str(out_prefix),
        "--output-json",
        str(out_json),
        "--db-path",
        str(args.db_path),
        "--db-glob",
        str(args.db_glob),
        "--seeds",
        str(args.seeds),
        "--test-days",
        str(args.test_days),
        "--warmup-days",
        str(args.warmup_days),
        "--modes",
        str(args.modes),
        "--max-blocks",
        str(args.max_blocks),
        *extra_args,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            f"Walk-forward run failed for {condition_name}.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return json.loads(out_json.read_text(encoding="utf-8"))


def _extract_metrics(result: dict) -> dict[str, float | str]:
    mode_payload = result["modes"]["atype3"]
    raw_row = mode_payload["raw_row_metrics"]
    focus_row = mode_payload["focus_row_metrics"]
    return {
        "recommended_mode_focus_nonA": result.get("recommended_mode_focus_nonA", ""),
        "raw_hit_at_1": float(raw_row.get("hit_at_1", 0.0)),
        "raw_auc": float(raw_row.get("auc", 0.0)),
        "raw_ndcg_at_2": float(raw_row.get("ndcg_at_2", 0.0)),
        "raw_ndcg_at_3": float(raw_row.get("ndcg_at_3", 0.0)),
        "focus_hit_at_1": float(focus_row.get("hit_at_1", 0.0)),
        "focus_auc": float(focus_row.get("auc", 0.0)),
        "focus_ndcg_at_2": float(focus_row.get("ndcg_at_2", 0.0)),
        "focus_ndcg_at_3": float(focus_row.get("ndcg_at_3", 0.0)),
        "raw_overall_mean": float(mode_payload["raw"]["overall"]["mean"]),
        "focus_overall_mean": float(mode_payload["focus_nonA"]["overall"]["mean"]),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, float | str]] = []
    for condition_name, extra_args in CONDITIONS:
        print(f"=== Running {condition_name} ===")
        result = _run_walk_forward(args, condition_name, extra_args)
        metrics = _extract_metrics(result)
        rows.append({"condition": condition_name, **metrics})
        print(metrics)

    df = pd.DataFrame(rows)
    out_csv = output_dir / "ablation_comparison.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    if len(df) == 2:
        base = df.iloc[0]
        compare = df.iloc[1]
        print("=== Delta vs without_position ===")
        print(
            {
                "focus_hit_at_1_delta": float(compare["focus_hit_at_1"]) - float(base["focus_hit_at_1"]),
                "focus_auc_delta": float(compare["focus_auc"]) - float(base["focus_auc"]),
                "focus_ndcg_at_2_delta": float(compare["focus_ndcg_at_2"]) - float(base["focus_ndcg_at_2"]),
                "focus_ndcg_at_3_delta": float(compare["focus_ndcg_at_3"]) - float(base["focus_ndcg_at_3"]),
                "focus_overall_mean_delta": float(compare["focus_overall_mean"]) - float(base["focus_overall_mean"]),
            }
        )
    print(f"Saved: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
