from __future__ import annotations

import argparse
import calendar
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "ml" / "analysis" / "results" / "gogo3_event_day_strategy"

HALL_SPECS: dict[str, dict[str, object]] = {
    "kamata7": {
        "label": "蒲田7",
        "db_path": PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db",
    },
    "zashiti": {
        "label": "ザシティ",
        "db_path": PROJECT_ROOT / "db" / "ザ-シティ-ベルシティ雑色店.db",
    },
    "lategap": {
        "label": "レイトギャップ",
        "db_path": PROJECT_ROOT / "db" / "レイトギャップ平和島.db",
    },
    "hiroki": {
        "label": "ヒロキ",
        "db_path": PROJECT_ROOT / "db" / "ヒロキ東口店.db",
    },
}

CATEGORY_ORDER = ["is_7suffix", "is_1suffix", "is_zorome", "is_strong_zorome", "is_month_end"]


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_label(hall_slug: str) -> str:
    return str(HALL_SPECS[hall_slug]["label"])


def _hall_db_path(hall_slug: str) -> Path:
    return Path(HALL_SPECS[hall_slug]["db_path"])


def _calendar_flags(date_dt: pd.Timestamp) -> dict[str, int]:
    day = int(date_dt.day)
    month_end = int(calendar.monthrange(int(date_dt.year), int(date_dt.month))[1])
    is_7suffix = int(day in {7, 17, 27})
    is_1suffix = int(day in {1, 11, 21, 31})
    is_zorome = int(day in {11, 22})
    is_strong_zorome = int(day == int(date_dt.month))
    is_month_end = int(day == month_end)
    is_any_event = int(is_7suffix or is_1suffix or is_zorome or is_strong_zorome or is_month_end or day == 30)
    return {
        "is_any_event": is_any_event,
        "is_7suffix": is_7suffix,
        "is_1suffix": is_1suffix,
        "is_zorome": is_zorome,
        "is_strong_zorome": is_strong_zorome,
        "is_month_end": is_month_end,
    }


def _normalize_frame(frame: pd.DataFrame, *, hall_slug: str) -> pd.DataFrame:
    work = frame.copy()
    required = ["date", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    missing = [column for column in required if column not in work.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")

    work = work.loc[:, required].copy()
    work["date"] = pd.to_numeric(work["date"], errors="coerce").astype("Int64")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce").astype("Int64")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["machine_name"] = work["machine_name"].astype(str)
    work = work.dropna(subset=["date", "machine_number", "games_normalized", "diff_coins_normalized"]).copy()
    work["date"] = work["date"].astype(int).astype(str).str.zfill(8)
    work["machine_number"] = work["machine_number"].astype(int)
    work["games_normalized"] = work["games_normalized"].astype(float)
    work["diff_coins_normalized"] = work["diff_coins_normalized"].astype(float)

    if hall_slug == "kamata7":
        date_suffix = work["date"].astype(str).str[-4:]
        work = work.loc[~(date_suffix.eq("0707") | work["machine_number"].eq(2026))].copy()

    work = work.loc[work["games_normalized"].ge(500)].copy()
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work = work.dropna(subset=["date_dt"]).copy()
    return work


def _load_hall_frame(hall_slug: str) -> pd.DataFrame:
    db_path = _hall_db_path(hall_slug)
    query = """
        SELECT date, machine_number, machine_name, games_normalized, diff_coins_normalized
        FROM machine_detailed_results
    """
    with sqlite3.connect(str(db_path)) as con:
        frame = pd.read_sql_query(query, con)
    return frame


def _daily_payout(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "daily_payout", "sum_games", "sum_diff", "n_rows"])
    daily = (
        frame.groupby("date", as_index=False)
        .agg(
            sum_games=("games_normalized", "sum"),
            sum_diff=("diff_coins_normalized", "sum"),
            n_rows=("machine_number", "size"),
        )
        .copy()
    )
    daily["daily_payout"] = (1.0 + daily["sum_diff"] / (3.0 * daily["sum_games"])) * 100.0
    return daily.loc[:, ["date", "daily_payout", "sum_games", "sum_diff", "n_rows"]].copy()


def _add_calendar_columns(daily: pd.DataFrame) -> pd.DataFrame:
    work = daily.copy()
    if work.empty:
        for column in [
            "is_any_event",
            "is_7suffix",
            "is_1suffix",
            "is_zorome",
            "is_strong_zorome",
            "is_month_end",
        ]:
            work[column] = pd.Series(dtype=int)
        return work

    flags = work["date"].map(lambda value: _calendar_flags(pd.Timestamp(str(value)))).apply(pd.Series)
    work = pd.concat([work, flags], axis=1)
    return work


def _resample_indices(n: int, rng: np.random.Generator, block_size: int) -> np.ndarray:
    if n <= 0:
        return np.array([], dtype=int)
    if n == 1:
        return np.array([0], dtype=int)
    indices: list[int] = []
    while len(indices) < n:
        start = int(rng.integers(0, n))
        for offset in range(block_size):
            indices.append((start + offset) % n)
            if len(indices) >= n:
                break
    return np.asarray(indices[:n], dtype=int)


def _bootstrap_mean_ci(
    values: np.ndarray, *, n_bootstrap: int = 2000, block_size: int = 7, seed: int = 42
) -> dict[str, float]:
    clean = np.asarray(values, dtype=float)
    clean = clean[~np.isnan(clean)]
    if len(clean) == 0:
        return {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"), "n": 0}
    if len(clean) == 1:
        value = float(clean[0])
        return {"mean": value, "ci_lower": value, "ci_upper": value, "n": 1}

    rng = np.random.default_rng(seed)
    boot_means: list[float] = []
    for _ in range(n_bootstrap):
        sample_idx = _resample_indices(len(clean), rng, block_size)
        boot_means.append(float(np.mean(clean[sample_idx])))
    return {
        "mean": float(np.mean(clean)),
        "ci_lower": float(np.percentile(boot_means, 2.5)),
        "ci_upper": float(np.percentile(boot_means, 97.5)),
        "n": int(len(clean)),
    }


def _bootstrap_group_diff(
    event_values: np.ndarray,
    non_event_values: np.ndarray,
    *,
    n_bootstrap: int = 2000,
    block_size: int = 7,
    seed: int = 42,
) -> dict[str, float]:
    event_clean = np.asarray(event_values, dtype=float)
    event_clean = event_clean[~np.isnan(event_clean)]
    non_event_clean = np.asarray(non_event_values, dtype=float)
    non_event_clean = non_event_clean[~np.isnan(non_event_clean)]
    if len(event_clean) == 0 or len(non_event_clean) == 0:
        return {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan")}

    observed = float(np.mean(event_clean) - np.mean(non_event_clean))
    if len(event_clean) == 1 and len(non_event_clean) == 1:
        return {"mean": observed, "ci_lower": observed, "ci_upper": observed}

    rng = np.random.default_rng(seed)
    boot: list[float] = []
    for _ in range(n_bootstrap):
        event_idx = _resample_indices(len(event_clean), rng, block_size)
        non_event_idx = _resample_indices(len(non_event_clean), rng, block_size)
        boot.append(float(np.mean(event_clean[event_idx]) - np.mean(non_event_clean[non_event_idx])))
    return {
        "mean": observed,
        "ci_lower": float(np.percentile(boot, 2.5)),
        "ci_upper": float(np.percentile(boot, 97.5)),
    }


def _bootstrap_did(
    event_gogo3: np.ndarray,
    non_event_gogo3: np.ndarray,
    event_all: np.ndarray,
    non_event_all: np.ndarray,
    *,
    n_bootstrap: int = 2000,
    block_size: int = 7,
    seed: int = 42,
) -> dict[str, float]:
    gogo3_event = np.asarray(event_gogo3, dtype=float)
    gogo3_event = gogo3_event[~np.isnan(gogo3_event)]
    gogo3_non_event = np.asarray(non_event_gogo3, dtype=float)
    gogo3_non_event = gogo3_non_event[~np.isnan(gogo3_non_event)]
    all_event = np.asarray(event_all, dtype=float)
    all_event = all_event[~np.isnan(all_event)]
    all_non_event = np.asarray(non_event_all, dtype=float)
    all_non_event = all_non_event[~np.isnan(all_non_event)]
    if len(gogo3_event) == 0 or len(gogo3_non_event) == 0 or len(all_event) == 0 or len(all_non_event) == 0:
        return {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan")}

    observed = float((np.mean(gogo3_event) - np.mean(gogo3_non_event)) - (np.mean(all_event) - np.mean(all_non_event)))
    if len(gogo3_event) == 1 and len(gogo3_non_event) == 1 and len(all_event) == 1 and len(all_non_event) == 1:
        return {"mean": observed, "ci_lower": observed, "ci_upper": observed}

    rng = np.random.default_rng(seed)
    boot: list[float] = []
    for _ in range(n_bootstrap):
        event_idx = _resample_indices(len(gogo3_event), rng, block_size)
        non_event_idx = _resample_indices(len(gogo3_non_event), rng, block_size)
        boot.append(
            float(
                (np.mean(gogo3_event[event_idx]) - np.mean(gogo3_non_event[non_event_idx]))
                - (np.mean(all_event[event_idx]) - np.mean(all_non_event[non_event_idx]))
            )
        )
    return {
        "mean": observed,
        "ci_lower": float(np.percentile(boot, 2.5)),
        "ci_upper": float(np.percentile(boot, 97.5)),
    }


def _category_series(daily: pd.DataFrame, category: str) -> pd.Series:
    day = pd.to_datetime(daily["date"], format="%Y%m%d", errors="coerce").dt.day
    month = pd.to_datetime(daily["date"], format="%Y%m%d", errors="coerce").dt.month
    month_end = pd.to_datetime(daily["date"], format="%Y%m%d", errors="coerce").dt.days_in_month
    if category == "is_7suffix":
        return day.isin([7, 17, 27])
    if category == "is_1suffix":
        return day.isin([1, 11, 21, 31])
    if category == "is_zorome":
        return day.isin([11, 22])
    if category == "is_strong_zorome":
        return day.eq(month)
    if category == "is_month_end":
        return day.eq(month_end)
    raise KeyError(category)


def build_hall_result(hall_slug: str, frame: pd.DataFrame) -> dict[str, object]:
    normalized = _normalize_frame(frame, hall_slug=hall_slug)
    gogo3_daily = _daily_payout(normalized.loc[normalized["machine_name"].eq("ゴーゴージャグラー3")].copy())
    all_daily = _daily_payout(normalized)

    merged = gogo3_daily.merge(all_daily, on="date", how="inner", suffixes=("_gogo3", "_all"))
    merged = _add_calendar_columns(merged.loc[:, ["date", "daily_payout_gogo3", "daily_payout_all"]].copy())

    event_mask = merged["is_any_event"].astype(bool)
    simple_diff = _bootstrap_group_diff(
        merged.loc[event_mask, "daily_payout_gogo3"].to_numpy(dtype=float),
        merged.loc[~event_mask, "daily_payout_gogo3"].to_numpy(dtype=float),
    )
    simple_diff["n_event"] = int(event_mask.sum())
    simple_diff["n_non_event"] = int((~event_mask).sum())

    did = _bootstrap_did(
        merged.loc[event_mask, "daily_payout_gogo3"].to_numpy(dtype=float),
        merged.loc[~event_mask, "daily_payout_gogo3"].to_numpy(dtype=float),
        merged.loc[event_mask, "daily_payout_all"].to_numpy(dtype=float),
        merged.loc[~event_mask, "daily_payout_all"].to_numpy(dtype=float),
    )

    by_category: dict[str, dict[str, float | int]] = {}
    for category in CATEGORY_ORDER:
        category_mask = _category_series(merged, category)
        n_category = int(category_mask.sum())
        if n_category < 20:
            continue
        category_did = _bootstrap_did(
            merged.loc[category_mask, "daily_payout_gogo3"].to_numpy(dtype=float),
            merged.loc[~category_mask, "daily_payout_gogo3"].to_numpy(dtype=float),
            merged.loc[category_mask, "daily_payout_all"].to_numpy(dtype=float),
            merged.loc[~category_mask, "daily_payout_all"].to_numpy(dtype=float),
        )
        by_category[category] = {
            "mean": category_did["mean"],
            "ci_lower": category_did["ci_lower"],
            "ci_upper": category_did["ci_upper"],
            "n": n_category,
        }

    return {
        "hall": hall_slug,
        "hall_label": _hall_label(hall_slug),
        "simple_diff": simple_diff,
        "did": did,
        "by_category": by_category,
    }


def _verdict_from_ci(ci_lower: float, ci_upper: float) -> str:
    if np.isnan(ci_lower) or np.isnan(ci_upper):
        return "no_significant_divergence"
    if ci_lower > 0:
        return "positive_divergence"
    if ci_upper < 0:
        return "negative_divergence"
    return "no_significant_divergence"


def _format_float(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    return f"{float(numeric):.2f}"


def _render_summary_markdown(summary: pd.DataFrame) -> str:
    columns = [
        "hall",
        "simple_diff_mean",
        "simple_diff_ci_lower",
        "simple_diff_ci_upper",
        "did_mean",
        "did_ci_lower",
        "did_ci_upper",
        "verdict",
    ]
    lines = ["# GOGO3 Event Strategy Summary", ""]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines.extend([header, separator])
    for _, row in summary.loc[:, columns].iterrows():
        rendered = []
        for column in columns:
            value = row[column]
            if column == "hall" or column == "verdict":
                rendered.append(str(value))
            else:
                rendered.append(_format_float(value))
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_outputs_for_halls(hall_slugs: list[str]) -> tuple[pd.DataFrame, dict[str, dict[str, object]]]:
    summary_rows: list[dict[str, object]] = []
    hall_results: dict[str, dict[str, object]] = {}
    for hall_slug in hall_slugs:
        result = build_hall_result(hall_slug, _load_hall_frame(hall_slug))
        hall_results[hall_slug] = result
        summary_rows.append(
            {
                "hall": result["hall_label"],
                "simple_diff_mean": result["simple_diff"]["mean"],
                "simple_diff_ci_lower": result["simple_diff"]["ci_lower"],
                "simple_diff_ci_upper": result["simple_diff"]["ci_upper"],
                "did_mean": result["did"]["mean"],
                "did_ci_lower": result["did"]["ci_lower"],
                "did_ci_upper": result["did"]["ci_upper"],
                "verdict": _verdict_from_ci(result["did"]["ci_lower"], result["did"]["ci_upper"]),
            }
        )
    summary = pd.DataFrame(summary_rows)
    return summary, hall_results


def save_outputs(summary: pd.DataFrame, hall_results: dict[str, dict[str, object]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for hall_slug, result in hall_results.items():
        payload = {
            "hall": result["hall"],
            "hall_label": result["hall_label"],
            "simple_diff": result["simple_diff"],
            "did": result["did"],
            "by_category": result["by_category"],
        }
        _write_json(output_dir / f"{hall_slug}_gogo3_event_bootstrap.json", payload)
    csv_summary = summary.loc[
        :,
        [
            "hall",
            "simple_diff_mean",
            "simple_diff_ci_lower",
            "simple_diff_ci_upper",
            "did_mean",
            "did_ci_lower",
            "did_ci_upper",
        ],
    ].copy()
    _write_csv(output_dir / "gogo3_event_strategy_summary.csv", csv_summary)
    _write_text(output_dir / "gogo3_event_strategy_summary.md", _render_summary_markdown(summary))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GOGO3 event day strategy analysis")
    parser.add_argument("--halls", nargs="*", default=list(HALL_SPECS.keys()), choices=list(HALL_SPECS.keys()))
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    summary, hall_results = build_outputs_for_halls(list(args.halls))
    save_outputs(summary, hall_results, Path(args.output_dir))
    print(Path(args.output_dir) / "gogo3_event_strategy_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
