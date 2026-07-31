"""Durability check for the Rakuen A-day x technical-intervention x tail-7 finding.

This deliberately differs from ``rakuen_aday_tech3f_durability``: normal days
exclude both A days {11,22,30} and B days {5,15,25}, exactly matching the
original attribute scan's three-way ``day_type`` definition.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
OUT_DIR = PROJECT_ROOT / "eda" / "results" / "rakuen_aday_tech7_durability"
DATE_START = "20250101"
DATE_END = "20260705"
A_DDS = {11, 22, 30}
B_DDS = {5, 15, 25}
TARGET_DIGIT = 7
N_BOOT = 2000
SEED = 20260729
EXPECTED_LIFT = 1.656


def load_frame(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Load pre-renovation technical-intervention rows; no target-day cutoff."""
    query = """
        SELECT r.date, r.machine_number, r.machine_name,
               r.games_normalized AS games, r.diff_coins_normalized AS diff_coins,
               r.bb_count, r.rb_count,
               m.jug_flag, m.hana_flag, m.bt_flag
        FROM machine_detailed_results r
        LEFT JOIN machine_master m ON r.machine_name = m.machine_name_normalized
        WHERE r.date BETWEEN ? AND ?
          AND r.games_normalized > 0
    """
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as con:
        df = pd.read_sql_query(query, con, params=(DATE_START, DATE_END))
    if df.empty:
        raise RuntimeError("no rows loaded from the requested Rakuen period")
    for col in ("jug_flag", "hana_flag", "bt_flag"):
        df[col] = df[col].fillna(0).astype(int)
    df["category"] = np.select(
        [df.jug_flag.eq(1), df.hana_flag.eq(1), df.bt_flag.eq(1)],
        ["ジャグ", "ハナハナ", "技術介入"],
        default="AT一般",
    )
    df["rate"] = 100 + df.diff_coins / (3 * df.games) * 100
    df["bbrb"] = (df.bb_count.fillna(0) + df.rb_count.fillna(0)) / df.games * 1000
    # Center on all technical-intervention machines, never just the tail-7 subset.
    df["resid_d"] = df.rate - df.groupby(["date", "category"]).rate.transform("mean")
    df["bbrb_d"] = df.bbrb - df.groupby(["date", "category"]).bbrb.transform("mean")
    dt = pd.to_datetime(df.date, format="%Y%m%d")
    df["dd"] = dt.dt.day
    df["quarter"] = dt.dt.to_period("Q").astype(str)
    df["day_type"] = np.select([df.dd.isin(A_DDS), df.dd.isin(B_DDS)], ["A", "B"], default="normal")
    df["last_digit"] = df.machine_number % 10
    return df.loc[(df.category == "技術介入") & df.last_digit.eq(TARGET_DIGIT)].copy()


def cluster_boot_lift(subset: pd.DataFrame, column: str, rng: np.random.Generator) -> tuple[float, float, float]:
    """A-day minus normal-day lift and a machine-cluster bootstrap 95% CI."""
    a = (
        subset.loc[subset.day_type.eq("A")]
        .groupby("machine_number")[column]
        .apply(lambda values: values.dropna().to_numpy())
    )
    normal = (
        subset.loc[subset.day_type.eq("normal")]
        .groupby("machine_number")[column]
        .apply(lambda values: values.dropna().to_numpy())
    )
    a = a[a.map(len).gt(0)]
    normal = normal[normal.map(len).gt(0)]
    machines = np.array(sorted(set(a.index) | set(normal.index)))
    if len(machines) < 2 or a.empty or normal.empty:
        return (np.nan, np.nan, np.nan)
    point = float(np.concatenate(a.to_list()).mean() - np.concatenate(normal.to_list()).mean())
    boot = np.full(N_BOOT, np.nan)
    for index in range(N_BOOT):
        picked = rng.choice(machines, size=len(machines), replace=True)
        a_values = [a[machine] for machine in picked if machine in a.index]
        n_values = [normal[machine] for machine in picked if machine in normal.index]
        if a_values and n_values:
            boot[index] = np.concatenate(a_values).mean() - np.concatenate(n_values).mean()
    return (point, float(np.nanpercentile(boot, 2.5)), float(np.nanpercentile(boot, 97.5)))


def verdict(value: float, baseline: float) -> str:
    if not np.isfinite(value) or not np.isfinite(baseline) or np.sign(value) != np.sign(baseline):
        return "消滅"
    ratio = abs(value / baseline)
    return "生存" if ratio >= 0.60 else "弱化" if ratio >= 0.25 else "消滅"


def make_row(subset: pd.DataFrame, split_type: str, label: str, rng: np.random.Generator) -> dict[str, object]:
    lift, lift_lo, lift_hi = cluster_boot_lift(subset, "resid_d", rng)
    bbrb_lift, bbrb_lo, bbrb_hi = cluster_boot_lift(subset, "bbrb_d", rng)
    return {
        "split_type": split_type,
        "label": label,
        "n_machines": subset.machine_number.nunique(),
        "n_A": int(subset.day_type.eq("A").sum()),
        "n_normal": int(subset.day_type.eq("normal").sum()),
        "lift": lift,
        "lift_lo": lift_lo,
        "lift_hi": lift_hi,
        "sig": "*" if lift_lo > 0 or lift_hi < 0 else "",
        "bbrb_lift": bbrb_lift,
        "bbrb_lo": bbrb_lo,
        "bbrb_hi": bbrb_hi,
        "bbrb_sig": "*" if bbrb_lo > 0 or bbrb_hi < 0 else "",
    }


def print_table(frame: pd.DataFrame) -> None:
    columns = [
        "split_type",
        "label",
        "n_machines",
        "n_A",
        "n_normal",
        "lift",
        "lift_lo",
        "lift_hi",
        "sig",
        "bbrb_lift",
        "bbrb_lo",
        "bbrb_hi",
        "bbrb_sig",
    ]
    print(frame.loc[:, columns].to_string(index=False, float_format=lambda value: f"{value:+.3f}"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    frame = load_frame()
    if frame.machine_number.nunique() == 0:
        raise RuntimeError("no technical-intervention tail-7 machines found")
    print(
        f"技術介入×末尾{TARGET_DIGIT}: {frame.machine_number.nunique()}台 / {len(frame):,}行 "
        f"/ {frame.date.nunique()}日 / A={int(frame.day_type.eq('A').sum()):,}行 "
        f"B={int(frame.day_type.eq('B').sum()):,}行 normal={int(frame.day_type.eq('normal').sum()):,}行"
    )

    rows = [make_row(frame, "全期間", "A vs normal（B除外）", rng)]
    date_values = np.sort(frame.date.unique())
    midpoint = date_values[len(date_values) // 2]
    rows.extend(
        [
            make_row(frame[frame.date.lt(midpoint)], "split-half", f"前半(〜{midpoint})", rng),
            make_row(frame[frame.date.ge(midpoint)], "split-half", f"後半({midpoint}〜)", rng),
        ]
    )
    for quarter, subset in frame.groupby("quarter", sort=True):
        if int(subset.day_type.eq("A").sum()) >= 20:
            rows.append(make_row(subset, "四半期", str(quarter), rng))
    for dd in sorted(A_DDS):
        subset = frame[frame.dd.eq(dd) | frame.day_type.eq("normal")].copy()
        subset.loc[:, "day_type"] = np.where(subset.dd.eq(dd), "A", "normal")
        rows.append(make_row(subset, "A日内訳", f"DD{dd}", rng))

    period = pd.DataFrame(rows)
    ordered_columns = [
        "split_type",
        "label",
        "n_machines",
        "n_A",
        "n_normal",
        "lift",
        "lift_lo",
        "lift_hi",
        "sig",
        "bbrb_lift",
        "bbrb_lo",
        "bbrb_hi",
        "bbrb_sig",
    ]
    period = period.loc[:, ordered_columns]
    period.to_csv(OUT_DIR / "period_splits.csv", index=False, encoding="utf-8-sig")

    base = period.iloc[0]
    reproduced = abs(float(base.lift) - EXPECTED_LIFT) < 0.02
    print("\n=== period splits ===")
    print_table(period)
    print(
        f"\n元の発見値との比較: 再計算 lift={base.lift:+.3f}pp "
        f"CI [{base.lift_lo:+.3f}, {base.lift_hi:+.3f}] / BB+RB={base.bbrb_lift:+.3f}.\n"
        f"期待値 +{EXPECTED_LIFT:.3f}pp との差={base.lift - EXPECTED_LIFT:+.3f}pp -> "
        f"{'再現' if reproduced else '不一致（入力・定義を要確認）'}"
    )
    split_rows = period[period.split_type.isin(["split-half", "四半期", "A日内訳"])].copy()
    split_rows["verdict"] = split_rows.lift.map(lambda value: verdict(float(value), float(base.lift)))
    print("\n=== 基準値比の判定（機械割lift） ===")
    print(
        split_rows[["split_type", "label", "lift", "verdict"]].to_string(
            index=False, float_format=lambda value: f"{value:+.3f}"
        )
    )

    loo_rows = []
    for machine in sorted(frame.machine_number.unique()):
        subset = frame[frame.machine_number.ne(machine)]
        lift, _, _ = cluster_boot_lift(subset, "resid_d", rng)
        bbrb_lift, _, _ = cluster_boot_lift(subset, "bbrb_d", rng)
        loo_rows.append({"excluded_machine": int(machine), "lift": lift, "bbrb_lift": bbrb_lift})
    leave_one_out = pd.DataFrame(loo_rows, columns=["excluded_machine", "lift", "bbrb_lift"])
    leave_one_out.to_csv(OUT_DIR / "leave_one_out.csv", index=False, encoding="utf-8-sig")
    worst = leave_one_out.loc[leave_one_out.lift.idxmin()]
    worst_bbrb = leave_one_out.loc[leave_one_out.bbrb_lift.idxmin()]
    print(
        f"\nleave-one-machine-out 最悪機械割: 台{int(worst.excluded_machine)}を除外 -> "
        f"{worst.lift:+.3f}pp ({verdict(float(worst.lift), float(base.lift))})"
    )
    print(f"leave-one-machine-out 最悪BB+RB: 台{int(worst_bbrb.excluded_machine)}を除外 -> {worst_bbrb.bbrb_lift:+.3f}")
    print(f"\n出力: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
