from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.mitoya_umj_mister_common import RESULT_DIR, analyze_machine_numbers, load_frame

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


MODELS = [
    "\u30a6\u30eb\u30c8\u30e9\u30df\u30e9\u30af\u30eb\u30b8\u30e3\u30b0\u30e9\u30fc",
    "\u30df\u30b9\u30bf\u30fc\u30b8\u30e3\u30b0\u30e9\u30fc",
]


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _summary_row(model: str, result: dict[str, object]) -> dict[str, object]:
    machine_summary = result["machine_summary"]
    top_row = machine_summary.iloc[0] if not machine_summary.empty else None
    bottom_row = machine_summary.iloc[-1] if not machine_summary.empty else None
    return {
        "model": model,
        "machines": int(machine_summary["machine_number"].nunique()) if not machine_summary.empty else 0,
        "rows": int(machine_summary["rows"].sum()) if not machine_summary.empty else 0,
        "chi2_stat": float(result["chi2_stat"]),
        "chi2_p": float(result["chi2_p"]),
        "chi2_dof": float(result["chi2_dof"]),
        "chi2_expected_sparse_share": float(result["chi2_expected_sparse_share"]),
        "spearman_rho": float(result["spearman_rho"]),
        "spearman_p": float(result["spearman_p"]),
        "spearman_n_common": int(result["spearman_n_common"]),
        "top_machine_number": int(top_row["machine_number"]) if top_row is not None else pd.NA,
        "top_machine_rate": float(top_row["pooled_rb_rate"]) if top_row is not None else pd.NA,
        "bottom_machine_number": int(bottom_row["machine_number"]) if bottom_row is not None else pd.NA,
        "bottom_machine_rate": float(bottom_row["pooled_rb_rate"]) if bottom_row is not None else pd.NA,
        "overall_verdict": result["overall_verdict"],
    }


def main() -> int:
    result_dir = RESULT_DIR
    result_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, object]] = []
    detail_frames: list[pd.DataFrame] = []

    for model in MODELS:
        frame = load_frame(machine_names=[model])
        result = analyze_machine_numbers(frame)
        machine_summary = result["machine_summary"].copy()
        machine_summary.insert(0, "model", model)
        detail_frames.append(machine_summary)
        summary_rows.append(_summary_row(model, result))

        print(f"=== {model} ===")
        print(
            f"rows={len(frame)}, dates={frame['date'].nunique()}, machines={frame['machine_number'].nunique()}, "
            f"chi2_p={summary_rows[-1]['chi2_p']:.4g}, spearman_rho={summary_rows[-1]['spearman_rho']:.4f}"
        )
        print(
            machine_summary.head(5)
            .loc[:, ["machine_number", "rows", "dates", "games_sum", "rb_sum", "pooled_rb_rate"]]
            .to_string(index=False)
        )

    summary_df = pd.DataFrame(summary_rows)
    detail_df = pd.concat(detail_frames, ignore_index=True) if detail_frames else pd.DataFrame()

    _write_csv(summary_df, result_dir / "task_c_machine_number_summary.csv")
    _write_csv(detail_df, result_dir / "task_c_machine_number_detail.csv")

    print(f"written: {result_dir / 'task_c_machine_number_summary.csv'}")
    print(f"written: {result_dir / 'task_c_machine_number_detail.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
