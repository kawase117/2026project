from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from pandas.api.types import CategoricalDtype
from scipy.stats import kruskal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.core import HALL_DBS, compute_debut_features, load_hall_df, _epsilon_squared

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from sklearn.cluster import KMeans
except Exception:  # pragma: no cover - dependency guard
    KMeans = None


BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / "eda" / "results" / "grouping_eda" / "AC_interaction"

DEBUT_PHASE_LABELS = ["1-14日", "15-60日", "61-180日", "181日+"]
GAMES_TIER_LABELS = ["低稼働", "中稼働", "高稼働"]
COUNT_GROUP_ORDER = ["XXS", "XS", "S", "M", "L", "XL"]
COUNT_GROUP_PREFIXES = ["XS", "S", "M", "L", "XL"]
MIN_NOTE_ROWS = 30


@dataclass
class HallResult:
    hall: str
    debut_marginal: pd.DataFrame
    debut_games_cross: pd.DataFrame
    count_group_summary: pd.DataFrame
    debut_count_interaction: pd.DataFrame
    machine_count_clusters: pd.DataFrame
    kruskal_results: pd.DataFrame
    summary: dict[str, object]


def _fmt_number(value: float | int | np.integer | np.floating | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return f"{float(value):.{digits}f}"


def _render_table(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "_no rows_"
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in df.iterrows():
        values: list[str] = []
        for col in columns:
            value = row[col]
            if col in {"avg_diff", "avg_games", "H", "p_value", "epsilon_sq"} or "p値" in col or col.endswith(" ε²"):
                values.append(_fmt_number(value, digits=2))
            elif col == "plus_rate":
                values.append(_fmt_number(value, digits=1))
            elif col in {"n", "n_machines", "n_groups", "n_total"}:
                values.append(_fmt_number(value, digits=0))
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def _low_n_note(n_rows: int) -> str:
    return "low_n" if n_rows < MIN_NOTE_ROWS else ""


def _safe_cut(series: pd.Series, bins: list[float], labels: list[str]) -> pd.Series:
    out = pd.Series(index=series.index, dtype="object")
    non_na = series.dropna()
    if non_na.empty:
        return out
    cut = pd.cut(non_na, bins=bins, labels=labels, include_lowest=True, ordered=True)
    out.loc[cut.index] = cut.astype("object")
    return out


def _safe_qcut(series: pd.Series, labels: list[str]) -> pd.Series:
    out = pd.Series(index=series.index, dtype="object")
    non_na = series.dropna()
    if non_na.empty:
        return out
    if non_na.nunique() == 1:
        out.loc[non_na.index] = labels[0]
        return out
    try:
        cat = pd.qcut(non_na, q=min(len(labels), non_na.nunique()), duplicates="drop")
    except ValueError:
        ranked = non_na.rank(method="first")
        cat = pd.qcut(ranked, q=min(len(labels), ranked.nunique()), duplicates="drop")
    n_bins = len(cat.cat.categories)
    mapped_labels = labels[:n_bins]
    mapped = pd.Series([mapped_labels[code] for code in cat.cat.codes], index=cat.index, dtype="object")
    out.loc[mapped.index] = mapped
    return out


def _hall_order(selected_halls: Sequence[str] | None) -> list[str]:
    if selected_halls:
        ordered = [hall for hall in HALL_DBS if hall in selected_halls]
        missing = [hall for hall in selected_halls if hall not in HALL_DBS]
        if missing:
            raise ValueError(f"Unknown hall(s): {missing!r}")
        return ordered
    return list(HALL_DBS.keys())


def _prepare_hall_frame(hall: str) -> pd.DataFrame:
    df = load_hall_df(hall).copy()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = compute_debut_features(df, db_start_grace_days=0)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df["hall"] = hall
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df["machine_count"] = pd.to_numeric(df.get("machine_count"), errors="coerce")
    df["days_since_debut"] = pd.to_numeric(df.get("days_since_debut"), errors="coerce")
    df["pre_existing"] = df.get("pre_existing", False).fillna(False).astype(bool)
    return df.sort_values(["machine_name", "date", "machine_number"]).reset_index(drop=True)


def _daily_machine_frame(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["date", "machine_name"], as_index=False)
        .agg(
            diff=("diff", "mean"),
            games=("games", "mean"),
            machine_count=("machine_count", "median"),
            days_since_debut=("days_since_debut", "median"),
            pre_existing=("pre_existing", "max"),
        )
        .sort_values(["machine_name", "date"])
        .reset_index(drop=True)
    )


def _group_summary(df: pd.DataFrame, group_cols: list[str], hall: str) -> pd.DataFrame:
    summary = (
        df.dropna(subset=group_cols)
        .groupby(group_cols, observed=True)
        .agg(
            n=("diff", "size"),
            n_machines=("machine_name", "nunique"),
            avg_diff=("diff", "mean"),
            plus_rate=("diff", lambda s: float((s > 0).mean() * 100)),
            avg_games=("games", "mean"),
        )
        .reset_index()
    )
    summary["hall"] = hall
    summary["note"] = summary["n"].map(_low_n_note)
    summary["avg_diff"] = summary["avg_diff"].round(1)
    summary["plus_rate"] = summary["plus_rate"].round(1)
    summary["avg_games"] = summary["avg_games"].round(1)
    ordered_cols = ["hall", *group_cols, "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "note"]
    return summary[ordered_cols]


def _count_group_summary(df: pd.DataFrame, machine_counts: pd.DataFrame, hall: str) -> pd.DataFrame:
    summary = _group_summary(df, ["count_group"], hall=hall)
    count_ranges = (
        machine_counts.groupby("count_group", observed=True)["median_count"].agg(["min", "max"]).reset_index()
    )
    count_ranges["median_count_range"] = count_ranges.apply(
        lambda row: f"{_fmt_number(row['min'], 1)}-{_fmt_number(row['max'], 1)}", axis=1
    )
    summary = summary.merge(count_ranges[["count_group", "median_count_range"]], on="count_group", how="left")
    return summary[
        ["hall", "count_group", "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "median_count_range", "note"]
    ]


def _build_count_groups(machine_counts: pd.DataFrame) -> pd.DataFrame:
    if KMeans is None:
        raise RuntimeError("scikit-learn is required for KMeans clustering")

    out = machine_counts.copy()
    out["median_count"] = pd.to_numeric(out["median_count"], errors="coerce")
    out = out.dropna(subset=["median_count"]).copy()
    out = out.sort_values(["median_count", "machine_name"]).reset_index(drop=True)

    xxs = out[out["median_count"] <= 3].copy()
    xxs["count_group"] = "XXS"

    rest = out[out["median_count"] > 3].copy()
    if rest.empty:
        result = xxs.copy()
        result["count_group"] = result["count_group"].astype(CategoricalDtype(COUNT_GROUP_ORDER, ordered=True))
        return result.sort_values(["count_group", "median_count", "machine_name"]).reset_index(drop=True)

    distinct_counts = int(rest["median_count"].nunique())
    n_clusters = min(5, distinct_counts, len(rest))
    if n_clusters < 2:
        rest["count_group"] = "XS"
    else:
        model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        rest["cluster_id"] = model.fit_predict(rest[["median_count"]])
        centroids = model.cluster_centers_.reshape(-1)
        order = np.argsort(centroids)
        labels = COUNT_GROUP_PREFIXES[:n_clusters]
        label_map = {int(cluster_id): labels[pos] for pos, cluster_id in enumerate(order)}
        rest["count_group"] = rest["cluster_id"].map(label_map)

    result = pd.concat([xxs, rest], ignore_index=True)
    result["count_group"] = result["count_group"].astype(CategoricalDtype(COUNT_GROUP_ORDER, ordered=True))
    return result.sort_values(["count_group", "median_count", "machine_name"]).reset_index(drop=True)


def _kruskal_from_frame(df: pd.DataFrame, group_cols: list[str], value_col: str = "diff") -> dict[str, object]:
    valid = df[group_cols + [value_col]].dropna()
    groups = [grp[value_col].to_numpy() for _, grp in valid.groupby(group_cols, observed=True) if len(grp) >= 2]
    if len(groups) < 2:
        return {
            "H": np.nan,
            "p_value": np.nan,
            "epsilon_sq": np.nan,
            "n_groups": len(groups),
            "n_total": int(sum(len(g) for g in groups)),
            "significant": False,
        }
    h_stat, p_value = kruskal(*groups)
    n_total = int(sum(len(g) for g in groups))
    epsilon_sq = float(_epsilon_squared(float(h_stat), len(groups), n_total))
    return {
        "H": float(h_stat),
        "p_value": float(p_value),
        "epsilon_sq": epsilon_sq,
        "n_groups": len(groups),
        "n_total": n_total,
        "significant": bool(p_value < 0.05),
    }


def analyze_debut_marginal(hall: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = df.loc[~df["pre_existing"]].copy()
    work = work.dropna(subset=["days_since_debut"]).copy()
    work["debut_phase"] = _safe_cut(
        work["days_since_debut"],
        bins=[-0.5, 14, 60, 180, 99999],
        labels=DEBUT_PHASE_LABELS,
    )
    work["debut_phase"] = work["debut_phase"].astype(CategoricalDtype(DEBUT_PHASE_LABELS, ordered=True))
    summary = _group_summary(work, ["debut_phase"], hall=hall)
    return work, summary


def analyze_debut_games_cross(hall: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = df.loc[~df["pre_existing"]].copy()
    work = work.dropna(subset=["days_since_debut"]).copy()
    work["debut_phase"] = _safe_cut(
        work["days_since_debut"],
        bins=[-0.5, 14, 60, 180, 99999],
        labels=DEBUT_PHASE_LABELS,
    )
    work["debut_phase"] = work["debut_phase"].astype(CategoricalDtype(DEBUT_PHASE_LABELS, ordered=True))
    daily = _daily_machine_frame(work)
    daily["games_14d"] = daily.groupby("machine_name")["games"].transform(
        lambda s: s.shift(1).rolling(14, min_periods=3).mean()
    )
    daily["games_tier"] = _safe_qcut(daily["games_14d"], GAMES_TIER_LABELS)
    daily["games_tier"] = daily["games_tier"].astype(CategoricalDtype(GAMES_TIER_LABELS, ordered=True))
    merged = work.merge(
        daily[["date", "machine_name", "games_14d", "games_tier"]],
        on=["date", "machine_name"],
        how="left",
        validate="m:1",
    )
    summary = _group_summary(merged, ["debut_phase", "games_tier"], hall=hall)
    return merged, summary


def analyze_count_groups(hall: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    machine_counts = (
        df.groupby("machine_name", as_index=False)
        .agg(
            median_count=("machine_count", "median"),
            n_days=("date", "nunique"),
        )
        .dropna(subset=["median_count"])
        .sort_values(["median_count", "machine_name"])
        .reset_index(drop=True)
    )
    machine_counts = _build_count_groups(machine_counts)
    merged = df.merge(
        machine_counts[["machine_name", "median_count", "n_days", "count_group"]],
        on="machine_name",
        how="left",
        validate="m:1",
    )
    summary = _count_group_summary(merged, machine_counts, hall=hall)
    return merged, summary, machine_counts


def analyze_debut_count_cross(
    hall: str, df: pd.DataFrame, machine_counts: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = df.loc[~df["pre_existing"]].copy()
    work = work.dropna(subset=["days_since_debut"]).copy()
    work["debut_phase"] = _safe_cut(
        work["days_since_debut"],
        bins=[-0.5, 14, 60, 180, 99999],
        labels=DEBUT_PHASE_LABELS,
    )
    work["debut_phase"] = work["debut_phase"].astype(CategoricalDtype(DEBUT_PHASE_LABELS, ordered=True))
    merged = work.merge(
        machine_counts[["machine_name", "median_count", "n_days", "count_group"]],
        on="machine_name",
        how="left",
        validate="m:1",
    )
    summary = _group_summary(merged, ["debut_phase", "count_group"], hall=hall)
    return merged, summary


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _hall_paths() -> dict[str, Path]:
    return {
        "root": RESULTS_DIR,
        "report": RESULTS_DIR / "ac_interaction_report.md",
        "kruskal": RESULTS_DIR / "kruskal_wallis_results.csv",
    }


def run_hall(hall: str) -> HallResult | None:
    try:
        df = _prepare_hall_frame(hall)
    except FileNotFoundError as exc:
        print(f"[skip] {hall}: {exc}")
        return None

    debut_marginal_frame, debut_marginal_summary = analyze_debut_marginal(hall, df)
    debut_games_frame, debut_games_summary = analyze_debut_games_cross(hall, df)
    count_frame, count_summary, machine_counts = analyze_count_groups(hall, df)
    debut_count_frame, debut_count_summary = analyze_debut_count_cross(hall, df, machine_counts)

    kruskal_rows = [
        {"hall": hall, "test_name": "debut_phase", **_kruskal_from_frame(debut_marginal_frame, ["debut_phase"])},
        {"hall": hall, "test_name": "games_tier", **_kruskal_from_frame(debut_games_frame, ["games_tier"])},
        {"hall": hall, "test_name": "count_group", **_kruskal_from_frame(count_frame, ["count_group"])},
        {
            "hall": hall,
            "test_name": "debut_x_count",
            **_kruskal_from_frame(debut_count_frame, ["debut_phase", "count_group"]),
        },
    ]
    kruskal_results = pd.DataFrame(kruskal_rows)

    _write_csv(debut_marginal_summary, RESULTS_DIR / f"{hall}_debut_marginal.csv")
    _write_csv(debut_games_summary, RESULTS_DIR / f"{hall}_debut_games_cross.csv")
    _write_csv(count_summary, RESULTS_DIR / f"{hall}_count_group_summary.csv")
    _write_csv(debut_count_summary, RESULTS_DIR / f"{hall}_debut_count_interaction.csv")
    _write_csv(
        machine_counts.assign(hall=hall)[["hall", "machine_name", "median_count", "n_days", "count_group"]],
        RESULTS_DIR / f"{hall}_machine_count_clusters.csv",
    )

    latest_date = df["date"].max().date().isoformat()
    summary = {
        "hall": hall,
        "date_min": df["date"].min().date().isoformat(),
        "date_max": latest_date,
        "n_rows": int(len(df)),
        "n_machine_names": int(df["machine_name"].nunique()),
        "n_dates": int(df["date"].nunique()),
        "debut_p": float(kruskal_results.loc[kruskal_results["test_name"] == "debut_phase", "p_value"].iloc[0])
        if not kruskal_results.empty
        else np.nan,
        "count_p": float(kruskal_results.loc[kruskal_results["test_name"] == "count_group", "p_value"].iloc[0])
        if not kruskal_results.empty
        else np.nan,
        "interaction_p": float(kruskal_results.loc[kruskal_results["test_name"] == "debut_x_count", "p_value"].iloc[0])
        if not kruskal_results.empty
        else np.nan,
        "debut_eps": float(kruskal_results.loc[kruskal_results["test_name"] == "debut_phase", "epsilon_sq"].iloc[0])
        if not kruskal_results.empty
        else np.nan,
        "count_eps": float(kruskal_results.loc[kruskal_results["test_name"] == "count_group", "epsilon_sq"].iloc[0])
        if not kruskal_results.empty
        else np.nan,
        "interaction_eps": float(
            kruskal_results.loc[kruskal_results["test_name"] == "debut_x_count", "epsilon_sq"].iloc[0]
        )
        if not kruskal_results.empty
        else np.nan,
    }
    significant_any = any(bool(v) for v in kruskal_results["significant"].fillna(False).tolist())
    summary["decision"] = "一部有意" if significant_any else "全てn.s."

    return HallResult(
        hall=hall,
        debut_marginal=debut_marginal_summary,
        debut_games_cross=debut_games_summary,
        count_group_summary=count_summary,
        debut_count_interaction=debut_count_summary,
        machine_count_clusters=machine_counts.assign(hall=hall)[
            ["hall", "machine_name", "median_count", "n_days", "count_group"]
        ],
        kruskal_results=kruskal_results,
        summary=summary,
    )


def _load_result_from_csvs(hall: str) -> HallResult | None:
    paths = {
        "debut_marginal": RESULTS_DIR / f"{hall}_debut_marginal.csv",
        "debut_games_cross": RESULTS_DIR / f"{hall}_debut_games_cross.csv",
        "count_group_summary": RESULTS_DIR / f"{hall}_count_group_summary.csv",
        "debut_count_interaction": RESULTS_DIR / f"{hall}_debut_count_interaction.csv",
        "machine_count_clusters": RESULTS_DIR / f"{hall}_machine_count_clusters.csv",
    }
    if not all(path.exists() for path in paths.values()):
        return None

    kruskal_path = RESULTS_DIR / "kruskal_wallis_results.csv"
    kruskal_results = pd.read_csv(kruskal_path)
    kruskal_results = (
        kruskal_results[kruskal_results["hall"] == hall].copy() if kruskal_path.exists() else pd.DataFrame()
    )

    return HallResult(
        hall=hall,
        debut_marginal=pd.read_csv(paths["debut_marginal"]),
        debut_games_cross=pd.read_csv(paths["debut_games_cross"]),
        count_group_summary=pd.read_csv(paths["count_group_summary"]),
        debut_count_interaction=pd.read_csv(paths["debut_count_interaction"]),
        machine_count_clusters=pd.read_csv(paths["machine_count_clusters"]),
        kruskal_results=kruskal_results,
        summary={"hall": hall, "date_min": "", "date_max": "", "n_rows": 0, "n_machine_names": 0, "n_dates": 0},
    )


def build_report(results: list[HallResult], skipped: list[str]) -> str:
    lines: list[str] = [
        "# 層別クロス集計EDA",
        "",
        f"- generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- halls processed: {len(results)}",
    ]
    if skipped:
        lines.append(f"- skipped: {', '.join(skipped)}")

    lines.extend(["", "## サマリ"])
    summary_rows = []
    for result in results:
        summary_rows.append(
            {
                "hall": result.hall,
                "A(debut) p値": result.summary.get("debut_p", np.nan),
                "C(count) p値": result.summary.get("count_p", np.nan),
                "A×C p値": result.summary.get("interaction_p", np.nan),
                "A ε²": result.summary.get("debut_eps", np.nan),
                "C ε²": result.summary.get("count_eps", np.nan),
                "判定": result.summary.get("decision", ""),
            }
        )
    lines.append(
        _render_table(
            pd.DataFrame(summary_rows),
            ["hall", "A(debut) p値", "C(count) p値", "A×C p値", "A ε²", "C ε²", "判定"],
        )
    )
    lines.append("")

    section_specs = [
        (
            "## 1. 検証A: debut_phase の汎化確認",
            "debut_marginal",
            ["debut_phase", "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "note"],
        ),
        (
            "## 1-2. debut_phase × games_tier",
            "debut_games_cross",
            ["debut_phase", "games_tier", "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "note"],
        ),
        (
            "## 2. 検証C: count_group の汎化確認",
            "count_group_summary",
            ["count_group", "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "median_count_range", "note"],
        ),
        (
            "## 3. A×C: debut_phase × count_group",
            "debut_count_interaction",
            ["debut_phase", "count_group", "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "note"],
        ),
    ]

    for title, attr, columns in section_specs:
        lines.append(title)
        for result in results:
            frame = getattr(result, attr).copy()
            lines.append(f"### {result.hall}")
            lines.append(_render_table(frame, columns))
            lines.append("")

    lines.append("## 4. Kruskal-Wallis")
    lines.append(
        _render_table(
            pd.concat([r.kruskal_results for r in results], ignore_index=True) if results else pd.DataFrame(),
            ["hall", "test_name", "H", "p_value", "epsilon_sq", "n_groups", "n_total", "significant"],
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def write_all_hall_outputs(results: list[HallResult]) -> None:
    if not results:
        return
    _write_csv(
        pd.concat([r.debut_marginal for r in results], ignore_index=True), RESULTS_DIR / "all_halls_debut_marginal.csv"
    )
    _write_csv(
        pd.concat([r.debut_games_cross for r in results], ignore_index=True),
        RESULTS_DIR / "all_halls_debut_games_cross.csv",
    )
    _write_csv(
        pd.concat([r.count_group_summary for r in results], ignore_index=True),
        RESULTS_DIR / "all_halls_count_group_summary.csv",
    )
    _write_csv(
        pd.concat([r.debut_count_interaction for r in results], ignore_index=True),
        RESULTS_DIR / "all_halls_debut_count_interaction.csv",
    )
    _write_csv(
        pd.concat([r.machine_count_clusters for r in results], ignore_index=True),
        RESULTS_DIR / "all_halls_machine_count_clusters.csv",
    )
    _write_csv(
        pd.concat([r.kruskal_results for r in results], ignore_index=True), RESULTS_DIR / "kruskal_wallis_results.csv"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="層別クロス集計EDA")
    parser.add_argument(
        "--hall",
        action="append",
        choices=list(HALL_DBS.keys()),
        help="one hall key from eda.core.HALL_DBS; repeatable. omit to process all halls",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="skip per-hall CSV generation and only write the report from existing CSVs",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selected_halls = _hall_order(args.hall)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results: list[HallResult] = []
    skipped: list[str] = []
    if not args.report_only:
        for hall in selected_halls:
            result = run_hall(hall)
            if result is None:
                skipped.append(hall)
                continue
            results.append(result)
        write_all_hall_outputs(results)
    else:
        for hall in selected_halls:
            result = _load_result_from_csvs(hall)
            if result is None:
                skipped.append(hall)
                continue
            results.append(result)

    report = build_report(results, skipped)
    report_path = RESULTS_DIR / "ac_interaction_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
