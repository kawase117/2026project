from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.metrics import roc_auc_score

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DEFAULT_HALLS = ["\u84b2\u75307", "\u84b2\u75301", "\u307f\u3068\u3084"]
DEFAULT_INPUT_DIR = Path("ml/experiments/label_redesign/results")
DEFAULT_OUTPUT_DIR = Path("ml/experiments/label_redesign/results")
DEFAULT_MIN_CELL_PAIRS = 30
DEFAULT_N_BOOTSTRAP = 1000
DEFAULT_RANDOM_SEED = 42

SUMMARY_COLUMNS = [
    "hall",
    "n_next_day_pairs",
    "corr_hit104_vs_next_payout",
    "corr_p_high_setting_vs_next_payout",
    "auc_hit104_predicts_next_hit104",
    "auc_p_high_setting_predicts_next_hit104",
    "auc_diff",
    "auc_diff_ci_lo",
    "auc_diff_ci_hi",
    "auc_diff_significant(bool)",
]

CELL_COLUMNS = [
    "hall",
    "dd",
    "machine_digit",
    "n_pairs",
    "auc_hit104",
    "auc_p_high_setting",
    "auc_diff",
    "note",
]


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_hall_frame(input_dir: Path, hall: str) -> pd.DataFrame:
    path = input_dir / f"{hall}_soft_label_comparison.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing input csv: {path}")

    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"date", "machine_name", "machine_number", "games", "hit104", "p_high_setting", "payout_rate"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")

    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games"] = pd.to_numeric(work["games"], errors="coerce")
    work["hit104"] = pd.to_numeric(work["hit104"], errors="coerce")
    work["p_high_setting"] = pd.to_numeric(work["p_high_setting"], errors="coerce")
    work["payout_rate"] = pd.to_numeric(work["payout_rate"], errors="coerce")
    work["dd"] = work["date"].dt.day.astype("Int64")
    work["machine_digit"] = work["machine_number"].mod(10).round().astype("Int64")
    return work


def _build_next_day_pairs(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    required = {"date", "machine_number", "games", "hit104", "p_high_setting", "payout_rate"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"frame is missing required columns: {missing}")

    work = frame.copy()
    if not pd.api.types.is_datetime64_any_dtype(work["date"]):
        work["date"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    if "dd" not in work.columns:
        work["dd"] = work["date"].dt.day.astype("Int64")
    if "machine_digit" not in work.columns:
        work["machine_digit"] = work["machine_number"].mod(10).round().astype("Int64")
    work = work.sort_values(["machine_number", "date", "machine_name"], kind="mergesort").reset_index(drop=True)

    rows: list[dict[str, object]] = []
    for machine_number, group in work.groupby("machine_number", sort=False):
        group = group.sort_values(["date", "machine_name"], kind="mergesort").reset_index(drop=True)
        for idx in range(len(group) - 1):
            current = group.iloc[idx]
            nxt = group.iloc[idx + 1]
            if pd.isna(current["date"]) or pd.isna(nxt["date"]):
                continue
            if (nxt["date"] - current["date"]).days != 1:
                continue
            if pd.isna(current["p_high_setting"]) or pd.isna(current["hit104"]) or pd.isna(current["payout_rate"]):
                continue
            if pd.isna(nxt["hit104"]) or pd.isna(nxt["payout_rate"]):
                continue

            rows.append(
                {
                    "hall": hall,
                    "date": current["date"],
                    "next_date": nxt["date"],
                    "machine_name": current["machine_name"],
                    "machine_number": int(machine_number) if pd.notna(machine_number) else pd.NA,
                    "dd": int(current["dd"]) if pd.notna(current["dd"]) else pd.NA,
                    "machine_digit": int(current["machine_digit"]) if pd.notna(current["machine_digit"]) else pd.NA,
                    "hit104": float(current["hit104"]),
                    "p_high_setting": float(current["p_high_setting"]),
                    "payout_rate": float(current["payout_rate"]),
                    "next_hit104": int(nxt["hit104"]),
                    "next_payout_rate": float(nxt["payout_rate"]),
                }
            )

    return pd.DataFrame(
        rows,
        columns=[
            "hall",
            "date",
            "next_date",
            "machine_name",
            "machine_number",
            "dd",
            "machine_digit",
            "hit104",
            "p_high_setting",
            "payout_rate",
            "next_hit104",
            "next_payout_rate",
        ],
    )


def _safe_pearson(x: pd.Series, y: pd.Series) -> float:
    valid = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(valid) < 2 or valid["x"].nunique() < 2 or valid["y"].nunique() < 2:
        return float("nan")
    return float(pearsonr(valid["x"], valid["y"])[0])


def _safe_auc(y_true: pd.Series, y_score: pd.Series) -> float:
    valid = pd.DataFrame(
        {"y_true": pd.to_numeric(y_true, errors="coerce"), "y_score": pd.to_numeric(y_score, errors="coerce")}
    ).dropna()
    if len(valid) < 2 or valid["y_true"].nunique() < 2:
        return float("nan")
    return float(roc_auc_score(valid["y_true"], valid["y_score"]))


def _bootstrap_auc_diff(
    pairs: pd.DataFrame,
    *,
    n_bootstrap: int,
    random_seed: int,
) -> tuple[float, float, float, bool]:
    if pairs.empty:
        return float("nan"), float("nan"), float("nan"), False

    base_hit = _safe_auc(pairs["next_hit104"], pairs["hit104"])
    base_p_high = _safe_auc(pairs["next_hit104"], pairs["p_high_setting"])
    base_diff = base_p_high - base_hit if pd.notna(base_hit) and pd.notna(base_p_high) else float("nan")

    if len(pairs) < 2 or pd.isna(base_diff):
        return base_diff, float("nan"), float("nan"), False

    rng = np.random.default_rng(random_seed)
    diffs: list[float] = []
    for _ in range(n_bootstrap):
        sample = pairs.iloc[rng.integers(0, len(pairs), size=len(pairs))]
        hit_auc = _safe_auc(sample["next_hit104"], sample["hit104"])
        p_high_auc = _safe_auc(sample["next_hit104"], sample["p_high_setting"])
        if pd.isna(hit_auc) or pd.isna(p_high_auc):
            continue
        diffs.append(float(p_high_auc - hit_auc))

    if not diffs:
        return base_diff, float("nan"), float("nan"), False

    ci_lo, ci_hi = np.percentile(np.asarray(diffs, dtype=float), [2.5, 97.5])
    significant = bool(ci_lo > 0 or ci_hi < 0)
    return float(base_diff), float(ci_lo), float(ci_hi), significant


def _summarize_hall(pairs: pd.DataFrame, *, hall: str, n_bootstrap: int, random_seed: int) -> pd.DataFrame:
    summary = {
        "hall": hall,
        "n_next_day_pairs": int(len(pairs)),
        "corr_hit104_vs_next_payout": _safe_pearson(pairs["hit104"], pairs["next_payout_rate"]),
        "corr_p_high_setting_vs_next_payout": _safe_pearson(pairs["p_high_setting"], pairs["next_payout_rate"]),
        "auc_hit104_predicts_next_hit104": _safe_auc(pairs["next_hit104"], pairs["hit104"]),
        "auc_p_high_setting_predicts_next_hit104": _safe_auc(pairs["next_hit104"], pairs["p_high_setting"]),
    }
    auc_diff, ci_lo, ci_hi, significant = _bootstrap_auc_diff(
        pairs,
        n_bootstrap=n_bootstrap,
        random_seed=random_seed,
    )
    summary.update(
        {
            "auc_diff": auc_diff,
            "auc_diff_ci_lo": ci_lo,
            "auc_diff_ci_hi": ci_hi,
            "auc_diff_significant(bool)": significant,
        }
    )
    return pd.DataFrame([summary], columns=SUMMARY_COLUMNS)


def _summarize_by_cell(
    pairs: pd.DataFrame,
    *,
    hall: str,
    min_cell_pairs: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if pairs.empty:
        return pd.DataFrame(columns=CELL_COLUMNS)

    for (dd, machine_digit), group in pairs.groupby(["dd", "machine_digit"], dropna=False, sort=True):
        n_pairs = int(len(group))
        note = ""
        auc_hit = float("nan")
        auc_p_high = float("nan")
        auc_diff = float("nan")

        if n_pairs < min_cell_pairs:
            note = f"excluded: n_pairs < {min_cell_pairs}"
        else:
            auc_hit = _safe_auc(group["next_hit104"], group["hit104"])
            auc_p_high = _safe_auc(group["next_hit104"], group["p_high_setting"])
            if pd.isna(auc_hit) or pd.isna(auc_p_high):
                note = "insufficient label diversity"
            else:
                auc_diff = float(auc_p_high - auc_hit)
                note = "included"

        rows.append(
            {
                "hall": hall,
                "dd": int(dd) if pd.notna(dd) else pd.NA,
                "machine_digit": int(machine_digit) if pd.notna(machine_digit) else pd.NA,
                "n_pairs": n_pairs,
                "auc_hit104": auc_hit,
                "auc_p_high_setting": auc_p_high,
                "auc_diff": auc_diff,
                "note": note,
            }
        )

    return pd.DataFrame(rows, columns=CELL_COLUMNS)


def run_analysis(
    halls: list[str],
    *,
    input_dir: Path,
    output_dir: Path,
    min_cell_pairs: int,
    n_bootstrap: int,
    random_seed: int,
) -> dict[str, pd.DataFrame]:
    input_dir = input_dir.resolve()
    output_dir = _ensure_directory(output_dir.resolve())

    outputs: dict[str, pd.DataFrame] = {}
    for hall in halls:
        frame = _read_hall_frame(input_dir, hall)
        pairs = _build_next_day_pairs(frame, hall=hall)
        summary = _summarize_hall(pairs, hall=hall, n_bootstrap=n_bootstrap, random_seed=random_seed)
        by_cell = _summarize_by_cell(pairs, hall=hall, min_cell_pairs=min_cell_pairs)

        summary_path = output_dir / f"{hall}_persistence_validation.csv"
        by_cell_path = output_dir / f"{hall}_persistence_validation_by_cell.csv"
        summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
        by_cell.to_csv(by_cell_path, index=False, encoding="utf-8-sig")

        outputs[f"{hall}_summary"] = summary
        outputs[f"{hall}_by_cell"] = by_cell

        summary_row = summary.iloc[0]
        if bool(summary_row["auc_diff_significant(bool)"]):
            if float(summary_row["auc_diff"]) > 0:
                direction = "p_high_setting"
            elif float(summary_row["auc_diff"]) < 0:
                direction = "hit104"
            else:
                direction = "no direction"
            interpretation = f"significant directional difference in favor of {direction}"
        else:
            interpretation = "no statistically significant directional difference"
        print(
            f"[{hall}] next_day_pairs={len(pairs)} summary_auc_diff={summary_row['auc_diff']:.4f} "
            f"ci=({summary_row['auc_diff_ci_lo']:.4f}, {summary_row['auc_diff_ci_hi']:.4f}) "
            f"significant={summary_row['auc_diff_significant(bool)']}"
        )
        print(f"  interpretation: {interpretation}")
        print(f"  wrote: {summary_path.name}")
        print(f"  wrote: {by_cell_path.name}")

    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate whether soft-label ranking persists to the next day.")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-cell-pairs", type=int, default=DEFAULT_MIN_CELL_PAIRS)
    parser.add_argument("--n-bootstrap", type=int, default=DEFAULT_N_BOOTSTRAP)
    parser.add_argument("--random-seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    run_analysis(
        args.halls,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        min_cell_pairs=args.min_cell_pairs,
        n_bootstrap=args.n_bootstrap,
        random_seed=args.random_seed,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
