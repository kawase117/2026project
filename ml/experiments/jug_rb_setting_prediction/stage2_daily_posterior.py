from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from scipy.stats import binom

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from .config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_DBS, HALL_SLUGS, JUGGLER_FAMILY_SPECS
from .stage1_machine_catalog import classify_machine_name

POSTERIOR_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "G",
    "rb",
    "bb",
    "p_set1",
    "p_set2",
    "p_set3",
    "p_set4",
    "p_set5",
    "p_set6",
    "p_high",
    "e_setting",
    "e_payout",
]


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, hall)


def _resolve_db_path(hall: str, db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    try:
        return HALL_DBS[hall]
    except KeyError as exc:  # pragma: no cover - argparse guards this path
        raise KeyError(f"unknown hall: {hall}") from exc


def _load_source(db_path: Path) -> pd.DataFrame:
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
                rb_count,
                bb_count
            FROM machine_detailed_results
            """,
            conn,
        )
    return frame


def _prepare_source(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["rb_count"] = pd.to_numeric(work["rb_count"], errors="coerce")
    work["bb_count"] = pd.to_numeric(work["bb_count"], errors="coerce")
    work = work.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "rb_count", "bb_count"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["machine_name"] = work["machine_name"].astype(str)
    work["hall"] = hall
    work["family_key"] = ""
    work["resolved_family_key"] = ""
    work["is_known_family"] = False
    work["is_unknown_family"] = False
    family_keys: list[str] = []
    resolved_family_keys: list[str] = []
    known_flags: list[bool] = []
    unknown_flags: list[bool] = []
    for machine_name in work["machine_name"].tolist():
        family_key, resolved_family_key, is_unknown_family = classify_machine_name(machine_name)
        family_keys.append(family_key)
        resolved_family_keys.append(resolved_family_key)
        known_flags.append(bool(resolved_family_key))
        unknown_flags.append(bool(is_unknown_family))
    work["family_key"] = family_keys
    work["resolved_family_key"] = resolved_family_keys
    work["is_known_family"] = known_flags
    work["is_unknown_family"] = unknown_flags
    return work.reset_index(drop=True)


def _apply_filters(frame: pd.DataFrame, *, hall: str) -> tuple[pd.DataFrame, dict[str, int]]:
    work = frame.copy()
    counts = {
        "raw_rows": int(len(work)),
        "non_juggler_rows": 0,
        "low_games_rows": 0,
        "unknown_family_rows": 0,
        "new_machine_rows": 0,
        "special_0707_rows": 0,
        "machine_2026_rows": 0,
    }

    before = len(work)
    work = work[work["machine_name"].str.contains("ジャグラー", na=False, regex=False)].copy()
    counts["non_juggler_rows"] = before - int(len(work))

    before = len(work)
    work = work[work["is_known_family"]].copy()
    counts["unknown_family_rows"] = before - int(len(work))

    before = len(work)
    work = work[work["games_normalized"].ge(500)].copy()
    counts["low_games_rows"] = before - int(len(work))
    if work.empty:
        return work, counts

    hall_first_date = work["date_dt"].min()
    first_seen = work.groupby(["machine_number", "machine_name"], sort=False)["date_dt"].transform("min")
    new_pair_age_days = (work["date_dt"] - first_seen).dt.days
    keep_new_pair = first_seen.eq(hall_first_date) | new_pair_age_days.ge(7)
    counts["new_machine_rows"] = int((~keep_new_pair).sum())
    work = work[keep_new_pair].copy()

    is_kamata7 = hall == "蒲田7" or _hall_slug(hall) == "kamata7"
    if is_kamata7:
        special_mask = work["date"].astype(str).str.endswith("0707")
        machine_2026_mask = work["machine_number"].eq(2026)
        counts["special_0707_rows"] = int(special_mask.sum())
        counts["machine_2026_rows"] = int(machine_2026_mask.sum())
        work = work.loc[~(special_mask | machine_2026_mask)].copy()

    return work.reset_index(drop=True), counts


def _posterior_for_row(row: pd.Series) -> dict[str, float]:
    g = int(row["games_normalized"])
    rb = int(row["rb_count"])
    bb = int(row["bb_count"])
    family_key = str(row["resolved_family_key"])
    spec = JUGGLER_FAMILY_SPECS[family_key]["settings"]
    log_prior = -math.log(6.0)
    log_probs: list[float] = []
    payout_rates: list[float] = []
    settings: list[int] = []
    for setting in range(1, 7):
        setting_spec = spec[setting]
        settings.append(setting)
        payout_rates.append(float(setting_spec["payout_rate"]))
        log_probs.append(
            float(
                binom.logpmf(rb, g, float(setting_spec["rb_probability"]))
                + binom.logpmf(bb, g, float(setting_spec["bb_probability"]))
                + log_prior
            )
        )
    norm = float(logsumexp(log_probs))
    probs = [float(math.exp(value - norm)) for value in log_probs]
    return {
        "p_set1": probs[0],
        "p_set2": probs[1],
        "p_set3": probs[2],
        "p_set4": probs[3],
        "p_set5": probs[4],
        "p_set6": probs[5],
        "p_high": float(sum(probs[3:])),
        "e_setting": float(sum(setting * prob for setting, prob in zip(settings, probs))),
        "e_payout": float(sum(payout * prob for payout, prob in zip(payout_rates, probs))),
        "_entropy": float(-sum(prob * math.log(prob) for prob in probs if prob > 0.0)),
    }


def _build_log_likelihood_matrix(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty:
        return np.empty((0, 6), dtype=float)

    work = frame.copy().reset_index(drop=True)
    work["resolved_family_key"] = work["resolved_family_key"].astype(str)
    g = pd.to_numeric(work["games_normalized"], errors="coerce").to_numpy(dtype=float)
    rb = pd.to_numeric(work["rb_count"], errors="coerce").to_numpy(dtype=float)
    bb = pd.to_numeric(work["bb_count"], errors="coerce").to_numpy(dtype=float)

    matrix = np.empty((len(work), 6), dtype=float)
    for family_key, indexer in work.groupby("resolved_family_key", sort=False).groups.items():
        spec = JUGGLER_FAMILY_SPECS[str(family_key)]["settings"]
        idx = np.asarray(list(indexer), dtype=int)
        family_g = g[idx]
        family_rb = rb[idx]
        family_bb = bb[idx]
        family_matrix = np.vstack(
            [
                binom.logpmf(family_rb, family_g, float(spec[setting]["rb_probability"]))
                + binom.logpmf(family_bb, family_g, float(spec[setting]["bb_probability"]))
                for setting in range(1, 7)
            ]
        ).T
        matrix[idx, :] = family_matrix
    return matrix


def _fit_empirical_prior(
    frame: pd.DataFrame,
    *,
    family_key: str,
    alpha: float = 2.0,
    max_iter: int = 500,
) -> dict[str, object]:
    rows = int(len(frame))
    if rows <= 0:
        pi = np.full(6, 1.0 / 6.0, dtype=float)
        return {
            "pi": pi,
            "iterations": 0,
            "converged": False,
            "loglik": float("nan"),
            "n_rows": 0,
        }

    log_likelihoods = _build_log_likelihood_matrix(frame)
    pi = np.full(6, 1.0 / 6.0, dtype=float)
    log_pi = np.log(pi)
    prev_loglik: float | None = None
    converged = False
    loglik = float("nan")

    for iteration in range(1, max_iter + 1):
        log_joint = log_likelihoods + log_pi[None, :]
        log_norm = logsumexp(log_joint, axis=1, keepdims=True)
        resp = np.exp(log_joint - log_norm)
        weights = resp.sum(axis=0) + (alpha - 1.0)
        weights = np.clip(weights, 1e-300, None)
        pi = weights / weights.sum()
        log_pi = np.log(pi)
        loglik = float(log_norm.sum())
        threshold = max(1e-4, 1e-6 * abs(loglik))
        if prev_loglik is not None and abs(loglik - prev_loglik) < threshold:
            converged = True
            break
        prev_loglik = loglik

    return {
        "pi": pi,
        "iterations": iteration,
        "converged": converged,
        "loglik": loglik,
        "n_rows": rows,
    }


def _fit_prior_bundle(frame: pd.DataFrame, *, prior_mode: str) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    if prior_mode not in {"uniform", "empirical"}:
        raise ValueError(f"unknown prior_mode: {prior_mode}")

    if frame.empty:
        empty = pd.DataFrame(
            columns=[
                "hall",
                "family_key",
                "family_name",
                "scope",
                "n_rows",
                "used_fallback",
                "alpha",
                "iterations",
                "converged",
                "loglik",
                "pi1",
                "pi2",
                "pi3",
                "pi4",
                "pi5",
                "pi6",
                "p_high_prior",
            ]
        )
        return empty, {"__hall__": np.full(6, 1.0 / 6.0, dtype=float)}

    hall_pi = np.full(6, 1.0 / 6.0, dtype=float)
    hall_diag = {"iterations": 0, "converged": True, "loglik": float("nan"), "n_rows": int(len(frame))}
    if prior_mode == "empirical":
        hall_fit = _fit_empirical_prior(frame, family_key="__hall__")
        hall_pi = np.asarray(hall_fit["pi"], dtype=float)
        hall_diag = hall_fit

    rows: list[dict[str, object]] = [
        {
            "hall": frame["hall"].iloc[0],
            "family_key": "__hall__",
            "family_name": "HALL_POOL",
            "scope": "hall",
            "n_rows": int(len(frame)),
            "used_fallback": False,
            "alpha": 2.0 if prior_mode == "empirical" else 0.0,
            "iterations": int(hall_diag["iterations"]),
            "converged": bool(hall_diag["converged"]),
            "loglik": float(hall_diag["loglik"]),
            "pi1": float(hall_pi[0]),
            "pi2": float(hall_pi[1]),
            "pi3": float(hall_pi[2]),
            "pi4": float(hall_pi[3]),
            "pi5": float(hall_pi[4]),
            "pi6": float(hall_pi[5]),
            "p_high_prior": float(hall_pi[3:].sum()),
        }
    ]

    prior_lookup: dict[str, np.ndarray] = {"__hall__": hall_pi}
    family_order = [family_key for family_key in sorted(frame["resolved_family_key"].dropna().astype(str).unique())]
    for family_key in family_order:
        family_frame = frame.loc[frame["resolved_family_key"].eq(family_key)].copy()
        used_fallback = prior_mode == "uniform" or len(family_frame) < 2000
        if prior_mode == "uniform":
            family_pi = np.full(6, 1.0 / 6.0, dtype=float)
            diag = {"iterations": 0, "converged": True, "loglik": float("nan")}
        elif used_fallback:
            family_pi = hall_pi
            diag = {
                "iterations": int(hall_diag["iterations"]),
                "converged": bool(hall_diag["converged"]),
                "loglik": float(hall_diag["loglik"]),
            }
        else:
            fit = _fit_empirical_prior(family_frame, family_key=family_key)
            family_pi = np.asarray(fit["pi"], dtype=float)
            diag = fit
        prior_lookup[family_key] = family_pi
        rows.append(
            {
                "hall": family_frame["hall"].iloc[0] if not family_frame.empty else frame["hall"].iloc[0],
                "family_key": family_key,
                "family_name": JUGGLER_FAMILY_SPECS[family_key]["family_name"],
                "scope": "hall" if used_fallback else "family",
                "n_rows": int(len(family_frame)),
                "used_fallback": bool(used_fallback),
                "alpha": 2.0 if prior_mode == "empirical" else 0.0,
                "iterations": int(diag["iterations"]),
                "converged": bool(diag["converged"]),
                "loglik": float(diag["loglik"]),
                "pi1": float(family_pi[0]),
                "pi2": float(family_pi[1]),
                "pi3": float(family_pi[2]),
                "pi4": float(family_pi[3]),
                "pi5": float(family_pi[4]),
                "pi6": float(family_pi[5]),
                "p_high_prior": float(family_pi[3:].sum()),
            }
        )
    prior_table = pd.DataFrame(rows)
    return prior_table, prior_lookup


def build_daily_posterior(frame: pd.DataFrame, *, prior_lookup: dict[str, np.ndarray]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=POSTERIOR_COLUMNS)
    work = frame.copy().reset_index(drop=False).rename(columns={"index": "__order"})
    rows: list[pd.DataFrame] = []
    for family_key, group in work.groupby("resolved_family_key", sort=False):
        spec = JUGGLER_FAMILY_SPECS[str(family_key)]["settings"]
        prior = np.asarray(prior_lookup.get(str(family_key), prior_lookup["__hall__"]), dtype=float)
        prior = prior / prior.sum()
        g = pd.to_numeric(group["games_normalized"], errors="coerce").to_numpy(dtype=float)
        rb = pd.to_numeric(group["rb_count"], errors="coerce").to_numpy(dtype=float)
        bb = pd.to_numeric(group["bb_count"], errors="coerce").to_numpy(dtype=float)
        setting_ids = np.arange(1, 7, dtype=float)
        payout_rates = np.array([float(spec[int(setting)]["payout_rate"]) for setting in setting_ids], dtype=float)
        rb_probs = np.array([float(spec[int(setting)]["rb_probability"]) for setting in setting_ids], dtype=float)
        bb_probs = np.array([float(spec[int(setting)]["bb_probability"]) for setting in setting_ids], dtype=float)
        log_probs = (
            np.vstack(
                [
                    binom.logpmf(rb, g, rb_prob) + binom.logpmf(bb, g, bb_prob)
                    for rb_prob, bb_prob in zip(rb_probs, bb_probs, strict=True)
                ]
            )
            + np.log(np.clip(prior, 1e-300, None))[:, None]
        )
        norm = logsumexp(log_probs, axis=0)
        probs = np.exp(log_probs - norm)
        entropies = -np.sum(np.where(probs > 0.0, probs * np.log(probs), 0.0), axis=0)
        output = pd.DataFrame(
            {
                "__order": group["__order"].to_numpy(),
                "date": group["date"].astype(str).to_numpy(),
                "machine_number": group["machine_number"].astype(int).to_numpy(),
                "machine_name": group["machine_name"].astype(str).to_numpy(),
                "G": group["games_normalized"].astype(int).to_numpy(),
                "rb": group["rb_count"].astype(int).to_numpy(),
                "bb": group["bb_count"].astype(int).to_numpy(),
                "p_set1": probs[0],
                "p_set2": probs[1],
                "p_set3": probs[2],
                "p_set4": probs[3],
                "p_set5": probs[4],
                "p_set6": probs[5],
                "p_high": probs[3:].sum(axis=0),
                "e_setting": np.dot(setting_ids, probs),
                "e_payout": np.dot(payout_rates, probs),
                "_entropy": entropies,
            }
        )
        rows.append(output)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=[*POSTERIOR_COLUMNS, "_entropy"])
    out = out.sort_values("__order", kind="mergesort").reset_index(drop=True)
    return out.loc[:, [*POSTERIOR_COLUMNS, "_entropy"]]


def _implied_rb_rate(pi: np.ndarray, *, family_key: str) -> float:
    spec = JUGGLER_FAMILY_SPECS[family_key]["settings"]
    rb_probs = np.array([float(spec[setting]["rb_probability"]) for setting in range(1, 7)], dtype=float)
    return float(np.dot(np.asarray(pi, dtype=float), rb_probs))


def _build_family_rb_sanity_table(posterior: pd.DataFrame, prior_table: pd.DataFrame) -> pd.DataFrame:
    if posterior.empty:
        return pd.DataFrame(
            columns=[
                "family_key",
                "family_name",
                "n_rows",
                "observed_rb_rate",
                "implied_rb_rate",
                "relative_deviation",
                "within_5pct",
                "needs_review",
                "used_fallback",
            ]
        )

    work = posterior.copy()
    resolved_keys = [
        classify_machine_name(str(machine_name))[1] for machine_name in work["machine_name"].astype(str).tolist()
    ]
    work["resolved_family_key"] = resolved_keys
    rows: list[dict[str, object]] = []
    prior_index = prior_table.set_index("family_key")
    for family_key, group in work.groupby("resolved_family_key", sort=True):
        if family_key not in prior_index.index:
            continue
        prior_row = prior_index.loc[family_key]
        prior = np.array([prior_row[f"pi{i}"] for i in range(1, 7)], dtype=float)
        observed_games = float(group["G"].sum())
        observed_rb = float(group["rb"].sum())
        observed_rb_rate = observed_rb / observed_games if observed_games > 0 else float("nan")
        implied_rb_rate = _implied_rb_rate(prior, family_key=str(family_key))
        relative_deviation = (
            (observed_rb_rate - implied_rb_rate) / implied_rb_rate if implied_rb_rate > 0 else float("nan")
        )
        rows.append(
            {
                "family_key": family_key,
                "family_name": prior_row["family_name"],
                "n_rows": int(len(group)),
                "observed_rb_rate": observed_rb_rate,
                "implied_rb_rate": implied_rb_rate,
                "relative_deviation": relative_deviation,
                "within_5pct": bool(0.0 <= relative_deviation <= 0.05) if not math.isnan(relative_deviation) else False,
                "needs_review": bool(relative_deviation < 0.0 or relative_deviation > 0.05)
                if not math.isnan(relative_deviation)
                else True,
                "used_fallback": bool(prior_row["used_fallback"]),
            }
        )
    return pd.DataFrame(rows)


def _format_exclusion_status(count: int) -> str:
    if count <= 0:
        return "N/A (no rows to exclude)"
    return f"True ({count} rows excluded)"


def _format_entropy_bins(posterior: pd.DataFrame) -> pd.DataFrame:
    if posterior.empty:
        return pd.DataFrame(columns=["g_bin", "n", "mean_entropy"])
    work = posterior.copy()
    bins = [-1, 999, 1999, 3999, 5999, float("inf")]
    labels = ["<1000", "1000-1999", "2000-3999", "4000-5999", "6000+"]
    work["g_bin"] = pd.cut(work["G"], bins=bins, labels=labels)
    summary = work.groupby("g_bin", dropna=False).agg(n=("G", "size"), mean_entropy=("_entropy", "mean")).reset_index()
    summary["g_bin"] = summary["g_bin"].astype(str)
    return summary


def build_stage2_outputs(
    *, db_path: Path, hall: str, prior_mode: str = "empirical"
) -> dict[str, pd.DataFrame | str | dict[str, int]]:
    raw = _load_source(db_path)
    prepared = _prepare_source(raw, hall=hall)
    filtered, counts = _apply_filters(prepared, hall=hall)
    prior_table, prior_lookup = _fit_prior_bundle(filtered, prior_mode=prior_mode)
    posterior = build_daily_posterior(filtered, prior_lookup=prior_lookup)
    if "_entropy" not in posterior.columns and not posterior.empty:
        p_values = posterior.loc[:, [f"p_set{i}" for i in range(1, 7)]].to_numpy(dtype=float)
        posterior = posterior.copy()
        posterior["_entropy"] = -np.sum(np.where(p_values > 0.0, p_values * np.log(p_values), 0.0), axis=1)
    elif "_entropy" not in posterior.columns:
        posterior = posterior.copy()
        posterior["_entropy"] = pd.Series(dtype=float)
    family_rb_sanity = _build_family_rb_sanity_table(posterior, prior_table)
    summary_lines = [
        f"# Stage 2 Daily Posterior - {hall}",
        f"- DB: `{db_path}`",
        f"- prior mode: {prior_mode}",
        "- Empirical prior: enabled (Dirichlet alpha=2, full-period fit)"
        if prior_mode == "empirical"
        else "- Empirical prior: disabled",
        "- Posterior prior source: family-specific priors for n_rows >= 2000; hall fallback otherwise",
        f"- raw rows: {counts['raw_rows']}",
        f"- kept rows: {len(filtered)}",
        f"- excluded non-juggler rows: {counts['non_juggler_rows']}",
        f"- excluded low-games rows: {counts['low_games_rows']}",
        f"- excluded unknown-family rows: {counts['unknown_family_rows']}",
        f"- excluded new-machine rows: {counts['new_machine_rows']}",
        f"- excluded 0707 rows: {_format_exclusion_status(counts['special_0707_rows'])}",
        f"- excluded machine 2026 rows: {_format_exclusion_status(counts['machine_2026_rows'])}",
        f"- mean p_high: {posterior['p_high'].mean():.6f} (consult if outside 0.02-0.40)"
        if not posterior.empty
        else "- mean p_high: nan",
        "",
        "## Prior Table",
        _entropy_table_markdown(
            prior_table.loc[
                :,
                [
                    "hall",
                    "family_key",
                    "family_name",
                    "scope",
                    "n_rows",
                    "used_fallback",
                    "iterations",
                    "converged",
                    "pi1",
                    "pi2",
                    "pi3",
                    "pi4",
                    "pi5",
                    "pi6",
                    "p_high_prior",
                ],
            ]
        ),
        "",
        "## Family RB Sanity (G-weighted rb/G)",
        _entropy_table_markdown(
            family_rb_sanity.loc[
                :,
                [
                    "family_key",
                    "family_name",
                    "n_rows",
                    "observed_rb_rate",
                    "implied_rb_rate",
                    "relative_deviation",
                    "within_5pct",
                    "needs_review",
                    "used_fallback",
                ],
            ]
        ),
        "",
        "## G Bin Entropy",
        _entropy_table_markdown(_format_entropy_bins(posterior)),
        "",
        "## Sanity Check",
        f"- approximate spec-consistency guard (0% to +5%): {bool(family_rb_sanity['needs_review'].eq(False).all()) if not family_rb_sanity.empty else False}",
        f"- family RB deviations: {', '.join(f'{row.family_key}={row.relative_deviation:+.1%}' for row in family_rb_sanity.itertuples(index=False)) if not family_rb_sanity.empty else 'n/a'}",
        f"- 0707 excluded: {_format_exclusion_status(counts['special_0707_rows'])}",
        f"- machine 2026 excluded: {_format_exclusion_status(counts['machine_2026_rows'])}",
    ]
    summary = "\n".join(summary_lines)
    return {
        "daily_posterior": posterior,
        "prior_table": prior_table,
        "summary": summary,
        "counts": counts,
        "entropy_bins": _format_entropy_bins(posterior),
    }


def _entropy_table_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    return "\n".join(
        ["| " + " | ".join(map(str, df.columns)) + " |"]
        + [
            "| " + " | ".join(map(lambda value: str(value), row)) + " |"
            for row in df.itertuples(index=False, name=None)
        ]
    )


def save_stage2_outputs(outputs: dict[str, pd.DataFrame | str | dict[str, int]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    posterior = outputs["daily_posterior"]
    prior_table = outputs["prior_table"]
    summary = outputs["summary"]
    assert isinstance(posterior, pd.DataFrame)
    assert isinstance(prior_table, pd.DataFrame)
    assert isinstance(summary, str)
    posterior.loc[:, POSTERIOR_COLUMNS].to_csv(
        output_dir / "stage2_daily_posterior.csv", index=False, encoding="utf-8-sig"
    )
    prior_table.to_csv(output_dir / "stage2_prior_table.csv", index=False, encoding="utf-8-sig")
    (output_dir / "stage2_summary.md").write_text(summary, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 2 juggler RB setting posterior")
    parser.add_argument("--hall", choices=tuple(HALL_DBS.keys()), default=DEFAULT_HALL)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--prior", choices=("uniform", "empirical"), default="empirical")
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    args = build_parser().parse_args(argv)
    db_path = _resolve_db_path(args.hall, args.db_path)
    output_dir = Path(args.output_dir) if args.output_dir is not None else DEFAULT_OUTPUT_ROOT / _hall_slug(args.hall)
    outputs = build_stage2_outputs(db_path=db_path, hall=args.hall, prior_mode=args.prior)
    save_stage2_outputs(outputs, output_dir)
    print(output_dir)
    print(output_dir / "stage2_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
