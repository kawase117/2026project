from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))
    from ml.experiments.jug_rb_setting_prediction.stage1_machine_catalog import classify_machine_name  # noqa: E402
else:  # pragma: no cover - exercised via package imports in tests
    from .stage1_machine_catalog import classify_machine_name  # noqa: E402


@dataclass(frozen=True)
class HallSpec:
    hall_slug: str
    db_path: Path
    stage2_csv: Path


HALL_SPECS: tuple[HallSpec, ...] = (
    HallSpec(
        "kamata7",
        PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "kamata7"
        / "stage2_daily_posterior.csv",
    ),
    HallSpec(
        "kamata1",
        PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "kamata1"
        / "stage2_daily_posterior.csv",
    ),
    HallSpec(
        "arrow",
        PROJECT_ROOT / "db" / "ARROW池上店.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "arrow"
        / "stage2_daily_posterior.csv",
    ),
    HallSpec(
        "lategap",
        PROJECT_ROOT / "db" / "レイトギャップ平和島.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "lategap"
        / "stage2_daily_posterior.csv",
    ),
    HallSpec(
        "mitoya",
        PROJECT_ROOT / "db" / "みとや大森町店.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "mitoya"
        / "stage2_daily_posterior.csv",
    ),
    HallSpec(
        "rakuen",
        PROJECT_ROOT / "db" / "楽園蒲田店.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "rakuen"
        / "stage2_daily_posterior.csv",
    ),
    HallSpec(
        "hiroki",
        PROJECT_ROOT / "db" / "ヒロキ東口店.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "hiroki"
        / "stage2_daily_posterior.csv",
    ),
    HallSpec(
        "zashiti",
        PROJECT_ROOT / "db" / "ザ-シティ-ベルシティ雑色店.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "zashiti"
        / "stage2_daily_posterior.csv",
    ),
    HallSpec(
        "kintoki",
        PROJECT_ROOT / "db" / "金時京急蒲田店.db",
        PROJECT_ROOT
        / "ml"
        / "experiments"
        / "results"
        / "jug_rb_setting_prediction"
        / "kintoki"
        / "stage2_daily_posterior.csv",
    ),
)

OUTPUT_PATH = (
    PROJECT_ROOT
    / "ml"
    / "experiments"
    / "results"
    / "jug_rb_setting_prediction"
    / "multi_hall"
    / "family_calibration_check.csv"
)
REQUIRED_STAGE2_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "e_payout",
]


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, encoding="utf-8-sig")
    missing = [column for column in REQUIRED_STAGE2_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")
    return frame


def _load_db_frame(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                date,
                machine_number,
                machine_name,
                games_normalized,
                diff_coins_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
    return frame


def _prepare_stage2(frame: pd.DataFrame, *, hall_slug: str) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = work["date"].astype(str)
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["e_payout"] = pd.to_numeric(work["e_payout"], errors="coerce")
    work["machine_name"] = work["machine_name"].astype(str)
    work = work.dropna(subset=["date", "machine_number", "machine_name", "e_payout"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    family_info = work["machine_name"].map(classify_machine_name)
    work["family_key"] = [item[0] if item[0] else "UNKNOWN" for item in family_info]
    work["hall_slug"] = hall_slug
    return work


def _prepare_db(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = work["date"].astype(str)
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["machine_name"] = work["machine_name"].astype(str)
    work = work.dropna(
        subset=["date", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    return work


def build_family_calibration_check() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for spec in HALL_SPECS:
        stage2 = _prepare_stage2(_load_csv(spec.stage2_csv), hall_slug=spec.hall_slug)
        db_frame = _prepare_db(_load_db_frame(spec.db_path))
        merged = stage2.merge(
            db_frame.loc[:, ["date", "machine_number", "games_normalized", "diff_coins_normalized"]],
            on=["date", "machine_number"],
            how="inner",
            validate="one_to_one",
        )
        if merged.empty:
            continue
        for family_key, group in merged.groupby("family_key", sort=True, dropna=False):
            games_sum = pd.to_numeric(group["games_normalized"], errors="coerce").sum()
            diff_sum = pd.to_numeric(group["diff_coins_normalized"], errors="coerce").sum()
            mean_e_payout = float(pd.to_numeric(group["e_payout"], errors="coerce").mean())
            realized_weighted = (
                float(((1.0 + diff_sum / (3.0 * games_sum)) * 100.0))
                if pd.notna(games_sum) and games_sum > 0
                else float("nan")
            )
            rows.append(
                {
                    "hall_slug": spec.hall_slug,
                    "family_key": str(family_key),
                    "n_rows": int(len(group)),
                    "mean_e_payout": mean_e_payout,
                    "realized_weighted": realized_weighted,
                    "gap_pp": mean_e_payout - realized_weighted,
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=["hall_slug", "family_key", "n_rows", "mean_e_payout", "realized_weighted", "gap_pp"]
        )
    return out.sort_values(["hall_slug", "family_key"], kind="mergesort").reset_index(drop=True)


def save_family_calibration_check(frame: pd.DataFrame, output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, encoding="utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Build family calibration check")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args(argv)

    frame = build_family_calibration_check()
    save_family_calibration_check(frame, args.output)
    print(f"[OK] wrote {args.output}")
    print(frame.head(10).to_csv(index=False).rstrip())
    abs_gap = (
        frame.assign(abs_gap=frame["gap_pp"].abs())
        .sort_values(["abs_gap", "hall_slug", "family_key"], ascending=[False, True, True], kind="mergesort")
        .head(3)
    )
    print("[TOP3]")
    print(abs_gap.loc[:, ["hall_slug", "family_key", "gap_pp"]].to_csv(index=False).rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
