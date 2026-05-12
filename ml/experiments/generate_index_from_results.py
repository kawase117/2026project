"""
Generate index.jsonl from existing experiment results.

This script scans ml/experiments/results/ for:
1. Legacy JSON files (exp_*.json, phase*.json, etc.)
2. New structured bundles ({experiment_id}/run.json)

And creates a unified index.jsonl for fast search/filter operations.

Run from project root:
    python ml/experiments/generate_index_from_results.py
"""

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results"
INDEX_PATH = RESULTS_DIR / "index.jsonl"


def extract_index_record(run_payload: dict[str, Any], path: Path) -> dict[str, Any]:
    """Extract minimal index record from a run payload."""
    result = run_payload.get("result", {})
    return {
        "run_id": run_payload.get("run_id") or run_payload.get("experiment_id"),
        "experiment_id": run_payload.get("experiment_id"),
        "timestamp": run_payload.get("timestamp"),
        "phase": run_payload.get("phase"),
        "task": run_payload.get("task"),
        "ml_model": run_payload.get("ml_model"),
        "groupby_strategy": run_payload.get("groupby_strategy"),
        "decision": run_payload.get("decision", "unreviewed"),
        "primary_metric": result.get("primary_metric"),
        "primary_value": result.get("primary_value"),
        "delta": result.get("delta"),
        "tags": run_payload.get("tags", []),
        "path": path.relative_to(RESULTS_DIR).as_posix(),
    }


def load_legacy_json(json_file: Path) -> dict[str, Any] | None:
    """Load and validate a legacy JSON file."""
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check if it's already a structured run payload (has 'decision' field)
        if "decision" in data:
            return data

        # For backward compat: old flat format. Convert to minimal payload.
        if "metrics" in data and "experiment_id" in data:
            metrics = data.get("metrics", {})
            primary_metric = "auc" if "auc" in metrics else list(metrics.keys())[0] if metrics else None
            return {
                "experiment_id": data.get("experiment_id"),
                "timestamp": data.get("timestamp"),
                "phase": data.get("phase"),
                "task": data.get("task"),
                "ml_model": data.get("ml_model"),
                "groupby_strategy": data.get("groupby_strategy"),
                "decision": "unreviewed",
                "result": {
                    "primary_metric": primary_metric,
                    "primary_value": metrics.get(primary_metric) if primary_metric else None,
                    "metrics": metrics,
                },
                "tags": [],
            }
    except Exception as e:
        print(f"⚠ Failed to load {json_file.name}: {e}")
        return None


def main():
    """Scan results directory and generate unified index."""
    if not RESULTS_DIR.exists():
        print(f"[ERROR] Results directory not found: {RESULTS_DIR}")
        return

    records = []
    seen = set()

    # 1. Scan new structure: {experiment_id}/run.json
    print(f"Scanning {RESULTS_DIR} for structured bundles...")
    for run_json in sorted(RESULTS_DIR.glob("*/run.json")):
        try:
            with open(run_json, "r", encoding="utf-8") as f:
                run_payload = json.load(f)

            exp_id = run_payload.get("experiment_id") or run_payload.get("run_id")
            if exp_id and exp_id not in seen:
                record = extract_index_record(run_payload, run_json)
                records.append(record)
                seen.add(exp_id)
                print(f"[OK] {exp_id}")
        except Exception as e:
            print(f"[WARN] Failed to load {run_json}: {e}")

    # 2. Scan legacy JSON files (top level)
    print(f"\nScanning {RESULTS_DIR} for legacy JSON files...")
    for json_file in sorted(RESULTS_DIR.glob("*.json")):
        if json_file.name == "index.jsonl":
            continue

        try:
            run_payload = load_legacy_json(json_file)
            if not run_payload:
                continue

            exp_id = run_payload.get("experiment_id")
            if exp_id and exp_id not in seen:
                record = extract_index_record(run_payload, json_file)
                records.append(record)
                seen.add(exp_id)
                print(f"[OK] {exp_id} (legacy)")
        except Exception as e:
            print(f"[WARN] Failed to process {json_file.name}: {e}")

    # 3. Write unified index
    if records:
        print(f"\nWriting {len(records)} records to index.jsonl...")
        lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
        INDEX_PATH.write_text(lines + "\n", encoding="utf-8")
        print(f"[OK] Index created: {INDEX_PATH}")
        print(f"\nSummary:")
        print(f"  Total records: {len(records)}")
        print(f"  Latest: {records[-1]['timestamp'] if records else 'N/A'}")

        # Sample decision distribution
        decision_counts = {}
        for r in records:
            d = r.get("decision", "unreviewed")
            decision_counts[d] = decision_counts.get(d, 0) + 1
        print(f"  Decision distribution: {decision_counts}")
    else:
        print("[WARN] No experiment records found")


if __name__ == "__main__":
    main()
