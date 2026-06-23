from __future__ import annotations

import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.cross_hall_pattern_verification import WINDOW_MONTHS, assign_period
from ml.analysis.kamata_corner_mirror_analysis import _read_machine_master_flags


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata17_payout104_eda"

DB_KAMATA7 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DB_KAMATA1 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
COORDS_KAMATA7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
COORDS_KAMATA7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
COORDS_KAMATA1_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata1.csv"

TEST_START = pd.Timestamp("2026-04-01")
MIN_GAMES = 1000
MAX_KAKUBAN = 20
MIN_EDA_N = 5
COINS_PER_GAME = 3
REVERSED_SECTIONS = {"2330-2351", "3191-3208", "3341-3362"}
EXCLUDED_KAMATA7 = {
    "2F": [(2187, 2195)],
    "3F": [(3191, 3208), (3209, 3217), (3400, 3401)],
}


@dataclass(frozen=True)
class HallSpec:
    hall_slug: str
    hall_name: str
    db_path: Path
    coords_paths: tuple[tuple[str, Path], ...]


@dataclass(frozen=True)
class SegmentSpec:
    segment_key: str
    floor: str
    machine_type: str | None = None
    side: str | None = None
    size_cats: tuple[str, ...] | None = None


HALL_SPECS: tuple[HallSpec, ...] = (
    HallSpec(
        hall_slug="kamata7",
        hall_name="蒲田七",
        db_path=DB_KAMATA7,
        coords_paths=(("2F", COORDS_KAMATA7_2F), ("3F", COORDS_KAMATA7_3F)),
    ),
    HallSpec(
        hall_slug="kamata1",
        hall_name="蒲田一",
        db_path=DB_KAMATA1,
        coords_paths=(("2F", COORDS_KAMATA1_2F),),
    ),
)

SEGMENT_SPECS: dict[str, tuple[SegmentSpec, ...]] = {
    "kamata7": (
        SegmentSpec("2F_N", "2F", machine_type="N"),
        SegmentSpec("3F_A", "3F", machine_type="A"),
        SegmentSpec("2F_L", "2F", side="L"),
        SegmentSpec("2F_R", "2F", side="R"),
        SegmentSpec("3F_L", "3F", side="L"),
        SegmentSpec("3F_R", "3F", side="R"),
    ),
    "kamata1": (
        SegmentSpec("2F_A", "2F", machine_type="A"),
        SegmentSpec("2F_A_Mid", "2F", machine_type="A", size_cats=("Mid",)),
        SegmentSpec("2F_N_L_nonMid", "2F", machine_type="N", side="L", size_cats=("Small", "Large")),
        SegmentSpec("2F_N_R_Large", "2F", machine_type="N", side="R", size_cats=("Large",)),
    ),
}


def _normalize_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


def _read_results(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT date, machine_number, machine_name, diff_coins_normalized, games_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
    if df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "machine_number",
                "machine_name",
                "diff_coins_normalized",
                "games_normalized",
            ]
        )
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["machine_name"] = df["machine_name"].astype(str)
    df["diff_coins_normalized"] = pd.to_numeric(df["diff_coins_normalized"], errors="coerce")
    df["games_normalized"] = pd.to_numeric(df["games_normalized"], errors="coerce")
    df = df.dropna(subset=["date", "machine_number", "machine_name", "diff_coins_normalized", "games_normalized"]).copy()
    df["machine_number"] = df["machine_number"].astype(int)
    df["date"] = df["date"].dt.normalize()
    df = df[df["games_normalized"] >= MIN_GAMES].copy()
    return df


def _read_coords(coords_paths: tuple[tuple[str, Path], ...]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for floor, path in coords_paths:
        coords = pd.read_csv(path)
        if coords.empty:
            continue
        coords = coords.copy()
        coords["floor"] = floor
        for col in ("machine_number", "X", "Y", "rank_from_min", "rank_from_max"):
            if col in coords.columns:
                coords[col] = pd.to_numeric(coords[col], errors="coerce")
        if "rank_from_min" not in coords.columns or "rank_from_max" not in coords.columns:
            if "section" in coords.columns:
                coords["rank_from_min"] = coords.groupby("section", dropna=False)["machine_number"].transform(
                    lambda s: s.rank(method="first", ascending=True)
                )
                coords["rank_from_max"] = coords.groupby("section", dropna=False)["machine_number"].transform(
                    lambda s: s.rank(method="first", ascending=False)
                )
            else:
                coords["rank_from_min"] = coords["machine_number"].rank(method="first", ascending=True)
                coords["rank_from_max"] = coords["machine_number"].rank(method="first", ascending=False)
        if "section" in coords.columns:
            coords["section_size"] = coords.groupby("section", dropna=False)["machine_number"].transform("size")
        else:
            coords["section_size"] = 1
        coords = coords.dropna(subset=["machine_number", "X", "Y", "rank_from_min", "rank_from_max"]).copy()
        coords["machine_number"] = coords["machine_number"].astype(int)
        coords["floor"] = coords["floor"].astype(str)
        frames.append(coords)
    if not frames:
        return pd.DataFrame(
            columns=[
                "machine_number",
                "X",
                "Y",
                "section",
                "rank_from_min",
                "rank_from_max",
                "section_size",
                "floor",
            ]
        )
    out = pd.concat(frames, ignore_index=True)
    dupes = out[out["machine_number"].duplicated(keep=False)]["machine_number"].dropna().astype(int).unique().tolist()
    if dupes:
        raise ValueError(f"Duplicate machine_number values found in coordinates: {sorted(dupes)}")
    return out


def _add_machine_type_flags(frame: pd.DataFrame, db_path: Path) -> pd.DataFrame:
    master = _read_machine_master_flags(db_path)
    out = frame.copy()
    out["machine_name_key"] = out["machine_name"].map(_normalize_text)
    if master.empty:
        out["jug_flag"] = 0
        out["hana_flag"] = 0
        out["bt_flag"] = 0
        return out

    master = master.copy()
    master["machine_name_key"] = master["machine_name_normalized"].map(_normalize_text)
    flag_cols = ["jug_flag", "hana_flag", "bt_flag"]
    master = (
        master[["machine_name_key", *flag_cols]]
        .groupby("machine_name_key", as_index=False)
        .max()
        .copy()
    )
    merged = out.merge(
        master,
        on="machine_name_key",
        how="left",
        validate="many_to_one",
    )
    for col in ("jug_flag", "hana_flag", "bt_flag"):
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0).astype(int)
    return merged


def _is_excluded_kamata7(row: pd.Series) -> bool:
    ranges = EXCLUDED_KAMATA7.get(str(row["floor"]), [])
    section = str(row.get("section", ""))
    if not section:
        return False
    try:
        section_num = int(section.split("-")[0])
    except Exception:
        return False
    return any(lo <= section_num <= hi for lo, hi in ranges)


def _assign_side_kamata7(floor: str, x: float) -> str:
    if floor == "2F":
        if x <= 17:
            return "L"
        if x >= 19:
            return "R"
    elif floor == "3F":
        if x <= 17:
            return "L"
        if x >= 23:
            return "R"
    return "E"


def _assign_side_kamata1(x: float) -> str:
    if x <= 17:
        return "L"
    if x >= 19:
        return "R"
    return "M"


def _assign_size_cat(section_size: int) -> str:
    if section_size <= 11:
        return "Small"
    if section_size <= 13:
        return "Mid"
    return "Large"


def _calc_payout_rate(games: pd.Series, diff: pd.Series) -> pd.Series:
    denom = pd.to_numeric(games, errors="coerce") * COINS_PER_GAME
    denom = denom.replace(0, np.nan)
    return ((denom + pd.to_numeric(diff, errors="coerce")) / denom) * 100


def _safe_mean(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    value = pd.to_numeric(series, errors="coerce").mean()
    return float(value) if pd.notna(value) else float("nan")


def _safe_sum(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    value = pd.to_numeric(series, errors="coerce").sum()
    return float(value) if pd.notna(value) else float("nan")


def _format_rate(value: float) -> str:
    if pd.isna(value):
        return "NaN"
    return f"{value:.1f}%"


def _format_diff_pp(value: float) -> str:
    if pd.isna(value):
        return "NaN"
    return f"{value:+.1f}pp"


def _load_hall_frame(spec: HallSpec) -> pd.DataFrame:
    results = _read_results(spec.db_path)
    coords = _read_coords(spec.coords_paths)
    if results.empty or coords.empty:
        return pd.DataFrame()

    merged = results.merge(coords, on="machine_number", how="inner", validate="many_to_one")
    if merged.empty:
        return merged

    merged = _add_machine_type_flags(merged, spec.db_path)
    merged["segment_floor"] = merged["floor"].astype(str)
    merged["payout_rate"] = _calc_payout_rate(merged["games_normalized"], merged["diff_coins_normalized"])
    merged["hit104"] = merged["payout_rate"].ge(104).fillna(False).astype(int)
    merged["dd"] = merged["date"].dt.day.astype(int)
    merged["section"] = merged["section"].fillna("").astype(str)

    if spec.hall_slug == "kamata7":
        merged = merged[~merged.apply(_is_excluded_kamata7, axis=1)].copy()
        merged["side"] = merged.apply(lambda r: _assign_side_kamata7(str(r["floor"]), float(r["X"])), axis=1)
        merged["machine_type"] = np.where(
            merged["floor"].eq("2F"),
            np.where((merged["jug_flag"].eq(1)) | (merged["hana_flag"].eq(1)) | (merged["bt_flag"].eq(1)), "A", "N"),
            np.where((merged["jug_flag"].eq(1)) | (merged["hana_flag"].eq(1)), "A", "N"),
        )
        merged["kakuban"] = np.where(
            merged["section"].isin(REVERSED_SECTIONS),
            merged["rank_from_max"],
            merged["rank_from_min"],
        )
    else:
        merged["side"] = merged["X"].apply(_assign_side_kamata1)
        merged["machine_type"] = np.where(
            (merged["jug_flag"].eq(1)) | (merged["hana_flag"].eq(1)) | (merged["bt_flag"].eq(1)),
            "A",
            "N",
        )
        merged["kakuban"] = merged["rank_from_min"]
        merged["size_cat"] = merged["section_size"].fillna(0).astype(int).map(_assign_size_cat)

    merged["kakuban"] = pd.to_numeric(merged["kakuban"], errors="coerce")
    merged = merged.dropna(subset=["kakuban"]).copy()
    merged["kakuban"] = merged["kakuban"].astype(int)
    merged = merged[(merged["kakuban"] >= 1) & (merged["kakuban"] <= MAX_KAKUBAN)].copy()
    return merged


def _apply_segment_filter(frame: pd.DataFrame, segment: SegmentSpec) -> pd.DataFrame:
    sub = frame[frame["floor"].eq(segment.floor)].copy()
    if segment.machine_type is not None:
        sub = sub[sub["machine_type"].eq(segment.machine_type)].copy()
    if segment.side is not None:
        sub = sub[sub["side"].eq(segment.side)].copy()
    if segment.size_cats is not None:
        sub = sub[sub["size_cat"].isin(segment.size_cats)].copy()
    return sub


def _get_periods(frame: pd.DataFrame) -> tuple[int, int] | None:
    if frame.empty:
        return None
    if "period" not in frame.columns:
        return None
    periods = sorted(pd.Series(frame["period"]).dropna().unique().tolist())
    if not periods:
        return None
    test_periods = sorted(frame.loc[frame["date"] >= TEST_START, "period"].dropna().unique().tolist())
    if not test_periods:
        return None
    test_period = int(test_periods[0])
    train_period = test_period - 1
    if train_period not in periods:
        return None
    return train_period, test_period


def _get_q5_names(frame: pd.DataFrame, train_period: int) -> set[str]:
    train = frame[frame["period"].eq(train_period)].copy()
    if train.empty:
        return set()
    agg = train.groupby("machine_name_key", as_index=False).agg(diff_sum=("diff_coins_normalized", "sum"))
    if agg.empty:
        return set()
    try:
        agg["quintile"] = pd.qcut(agg["diff_sum"], 5, labels=False, duplicates="drop") + 1
    except ValueError:
        return set()
    qmax = agg["quintile"].max()
    return set(agg.loc[agg["quintile"].eq(qmax), "machine_name_key"])


def _summarize_rate(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {
            "n": 0,
            "payout104_count": 0,
            "payout104_rate": float("nan"),
            "mean_diff": float("nan"),
        }
    n = int(len(frame))
    payout104_count = int(frame["hit104"].sum())
    payout104_rate = float(frame["hit104"].mean()) if n else float("nan")
    mean_diff = _safe_mean(frame["diff_coins_normalized"])
    return {
        "n": n,
        "payout104_count": payout104_count,
        "payout104_rate": payout104_rate,
        "mean_diff": mean_diff,
    }


def _build_kakuban_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for kakuban in range(1, MAX_KAKUBAN + 1):
        sub = frame[frame["kakuban"].eq(kakuban)].copy()
        stats = _summarize_rate(sub)
        rows.append(
            {
                "kakuban": kakuban,
                "n": stats["n"],
                "payout104_rate": stats["payout104_rate"],
                "payout104_count": stats["payout104_count"],
                "mean_diff": stats["mean_diff"],
            }
        )
    return pd.DataFrame(rows, columns=["kakuban", "n", "payout104_rate", "payout104_count", "mean_diff"])


def _build_kakuban_groups(frame: pd.DataFrame) -> pd.DataFrame:
    def group_label(k: int) -> str:
        if k == 1:
            return "1"
        if 2 <= k <= 4:
            return "2-4"
        if 5 <= k <= 9:
            return "5-9"
        return "10+"

    work = frame.copy()
    work["kakuban_group"] = work["kakuban"].map(group_label)
    order = ["1", "2-4", "5-9", "10+"]
    rows: list[dict[str, float | int | str]] = []
    for group in order:
        sub = work[work["kakuban_group"].eq(group)].copy()
        stats = _summarize_rate(sub)
        rows.append(
            {
                "kakuban_group": group,
                "n": stats["n"],
                "payout104_count": stats["payout104_count"],
                "payout104_rate": stats["payout104_rate"],
                "mean_diff": stats["mean_diff"],
            }
        )
    return pd.DataFrame(rows, columns=["kakuban_group", "n", "payout104_count", "payout104_rate", "mean_diff"])


def _build_dd_kakuban_cross(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, float | int]] = []
    for dd in range(1, 32):
        dd_frame = frame[frame["dd"].eq(dd)].copy()
        for kakuban in range(1, MAX_KAKUBAN + 1):
            sub = dd_frame[dd_frame["kakuban"].eq(kakuban)].copy()
            if len(sub) < MIN_EDA_N:
                continue
            stats = _summarize_rate(sub)
            rows.append(
                {
                    "dd": dd,
                    "kakuban": kakuban,
                    "n": stats["n"],
                    "payout104_rate": stats["payout104_rate"],
                    "payout104_count": stats["payout104_count"],
                    "mean_diff": stats["mean_diff"],
                }
            )
    cross = pd.DataFrame(rows, columns=["dd", "kakuban", "n", "payout104_rate", "payout104_count", "mean_diff"])
    if cross.empty:
        best = pd.DataFrame(columns=["dd", "best_kakuban", "payout104_rate", "n", "payout104_count", "mean_diff"])
        return cross, best

    sorted_cross = cross.sort_values(
        ["dd", "payout104_rate", "n", "kakuban"],
        ascending=[True, False, False, True],
    ).copy()
    best = (
        sorted_cross.groupby("dd", as_index=False)
        .first()[["dd", "kakuban", "payout104_rate", "n", "payout104_count", "mean_diff"]]
        .rename(columns={"kakuban": "best_kakuban"})
    )
    return cross, best


def _print_baseline(segment_frame: pd.DataFrame, q5_frame: pd.DataFrame) -> None:
    all_stats = _summarize_rate(segment_frame)
    q5_stats = _summarize_rate(q5_frame)
    print(
        f"ベースライン: 全台 104%率={_format_rate(all_stats['payout104_rate'] * 100 if pd.notna(all_stats['payout104_rate']) else np.nan)} "
        f"(n={all_stats['n']:,}) / "
        f"Q5 104%率={_format_rate(q5_stats['payout104_rate'] * 100 if pd.notna(q5_stats['payout104_rate']) else np.nan)} "
        f"(n={q5_stats['n']:,})"
    )


def _print_kakuban_groups(groups: pd.DataFrame, baseline_rate: float) -> None:
    if groups.empty:
        print("角番グループ別: データなし")
        return
    best_idx = None
    if groups["payout104_rate"].notna().any():
        best_idx = groups["payout104_rate"].astype(float).idxmax()
    print("\n角番グループ別:")
    for idx, row in groups.iterrows():
        rate_pct = row["payout104_rate"] * 100 if pd.notna(row["payout104_rate"]) else np.nan
        delta_pp = rate_pct - baseline_rate if pd.notna(rate_pct) and pd.notna(baseline_rate) else np.nan
        marker = " ★" if best_idx is not None and idx == best_idx else ""
        print(
            f"角番{row['kakuban_group']}: 104%率={_format_rate(rate_pct)} "
            f"(n={int(row['n']):,}) [vs全台 {_format_diff_pp(delta_pp)}]{marker}"
        )


def _print_dd_best(best: pd.DataFrame) -> None:
    print("\nDD別 Best角番 (104%率基準):")
    if best.empty:
        print("DD別 Best角番: データなし")
        return
    for dd in range(1, 32):
        row = best[best["dd"].eq(dd)]
        if row.empty:
            print(f"DD={dd}: 角番=NaN")
            continue
        rec = row.iloc[0]
        rate_pct = rec["payout104_rate"] * 100 if pd.notna(rec["payout104_rate"]) else np.nan
        print(
            f"DD={dd}: 角番={int(rec['best_kakuban'])} "
            f"(104%率={_format_rate(rate_pct)}, n={int(rec['n']):,})"
        )


def _write_segment_outputs(
    result_dir: Path,
    hall_slug: str,
    segment_key: str,
    kakuban_table: pd.DataFrame,
    cross_table: pd.DataFrame,
) -> None:
    kakuban_path = result_dir / f"kakuban_payout104_{hall_slug}_{segment_key}.csv"
    cross_path = result_dir / f"dd_kakuban_payout104_cross_{hall_slug}_{segment_key}.csv"
    kakuban_table.to_csv(kakuban_path, index=False, encoding="utf-8-sig")
    cross_table.to_csv(cross_path, index=False, encoding="utf-8-sig")


def analyze_hall(spec: HallSpec) -> None:
    print("\n" + "=" * 72)
    print(f"=== {spec.hall_name} ===")
    print("=" * 72)

    frame = _load_hall_frame(spec)
    if frame.empty:
        print("データなし")
        return

    frame["period"] = assign_period(frame["date"], WINDOW_MONTHS)
    period_bounds = frame.groupby("period")["date"].agg(["min", "max"])
    test_periods = frame.loc[frame["date"] >= TEST_START, "period"].dropna().unique()
    if len(test_periods) == 0:
        print("テスト期間(2026-04-01以降)が見つかりません")
        return
    test_period = int(sorted(test_periods)[0])
    train_period = test_period - 1
    if train_period not in period_bounds.index:
        print(f"学習期 period={train_period} が存在しません")
        return

    test_mask = frame["period"].eq(test_period)
    test_frame = frame[test_mask].copy()
    q5_names = _get_q5_names(frame, train_period)
    print(
        f"train_period={train_period} ({period_bounds.loc[train_period, 'min'].date()} ~ {period_bounds.loc[train_period, 'max'].date()})"
    )
    print(
        f"test_period={test_period} ({period_bounds.loc[test_period, 'min'].date()} ~ {period_bounds.loc[test_period, 'max'].date()})"
    )
    print(f"Q5機種数={len(q5_names)}")
    print(f"test rows={len(test_frame):,}, dates={test_frame['date'].nunique():,}")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    segments = SEGMENT_SPECS[spec.hall_slug]

    for segment in segments:
        segment_frame = _apply_segment_filter(test_frame, segment)
        segment_all = _apply_segment_filter(frame, segment)
        q5_frame = segment_frame[segment_frame["machine_name_key"].isin(q5_names)].copy()
        baseline_stats = _summarize_rate(segment_frame)
        baseline_rate = baseline_stats["payout104_rate"] * 100 if pd.notna(baseline_stats["payout104_rate"]) else np.nan

        print(f"\n--- セグメント: {segment.segment_key} ---")
        _print_baseline(segment_frame, q5_frame)

        kakuban_table = _build_kakuban_table(segment_frame)
        groups = _build_kakuban_groups(segment_frame)
        _print_kakuban_groups(groups, baseline_rate)

        cross_table, best_table = _build_dd_kakuban_cross(segment_all)
        _print_dd_best(best_table)

        _write_segment_outputs(RESULT_DIR, spec.hall_slug, segment.segment_key, kakuban_table, cross_table)


def main() -> None:
    for spec in HALL_SPECS:
        analyze_hall(spec)


if __name__ == "__main__":
    main()
