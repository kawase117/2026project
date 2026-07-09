from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from scipy.special import logsumexp
from scipy.stats import binom


def _create_stage2_sample_db(path: Path) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                games_normalized INTEGER,
                rb_count INTEGER,
                bb_count INTEGER
            )
            """
        )
        rows = [
            ("20260601", 1001, "マイジャグラーV", 1000, 3, 0),
            ("20260602", 1001, "マイジャグラーV", 1000, 3, 0),
        ]
        rows.extend([("20260601", 1002, "ゴーゴージャグラー3", 680, 2, 0) for _ in range(2001)])
        rows.extend(
            [
                ("20260601", 1003, "マイジャグラーV", 1000, 3, 0),
                ("20260602", 1003, "マイジャグラーV", 1000, 3, 0),
            ]
        )
        conn.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()


def _expected_posterior_from_prior(g: int, rb: int, bb: int, family_key: str, prior: list[float]) -> list[float]:
    from ml.experiments.jug_rb_setting_prediction.config import JUGGLER_FAMILY_SPECS

    spec = JUGGLER_FAMILY_SPECS[family_key]["settings"]
    log_probs = []
    for setting in range(1, 7):
        setting_spec = spec[setting]
        log_probs.append(
            binom.logpmf(rb, g, setting_spec["rb_probability"])
            + binom.logpmf(bb, g, setting_spec["bb_probability"])
            + math.log(prior[setting - 1])
        )
    norm = logsumexp(log_probs)
    return [float(math.exp(value - norm)) for value in log_probs]


def test_stage2_computes_daily_posteriors_and_summaries(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage2_daily_posterior as stage2

    db_path = tmp_path / "sample.db"
    _create_stage2_sample_db(db_path)

    outputs = stage2.build_stage2_outputs(db_path=db_path, hall="蒲田7")
    posterior = outputs["daily_posterior"]
    prior_table = outputs["prior_table"]
    summary = outputs["summary"]

    assert isinstance(posterior, pd.DataFrame)
    assert isinstance(prior_table, pd.DataFrame)
    assert {"family_key", "family_name", "scope", "n_rows", "pi1", "pi6", "p_high_prior"} <= set(prior_table.columns)
    assert {
        "date",
        "machine_number",
        "machine_name",
        "G",
        "rb",
        "bb",
        "p_set1",
        "p_set6",
        "p_high",
        "e_setting",
        "e_payout",
    } <= set(posterior.columns)
    assert len(posterior) == 2005
    assert posterior.loc[posterior["machine_number"].eq(1001), "date"].astype(str).tolist() == ["20260601", "20260602"]

    hall_prior = prior_table.loc[prior_table["family_key"].eq("__hall__")].iloc[0]
    hall_pi = [hall_prior[f"pi{i}"] for i in range(1, 7)]
    gogo_prior = prior_table.loc[prior_table["family_key"].eq("GOGO3")].iloc[0]
    gogo_pi = [gogo_prior[f"pi{i}"] for i in range(1, 7)]

    for _, row in posterior.loc[posterior["machine_number"].isin([1001, 1002, 1003])].head(4).iterrows():
        probs = [row[f"p_set{i}"] for i in range(1, 7)]
        assert sum(probs) == pytest.approx(1.0, rel=1e-9, abs=1e-9)
        assert row["p_high"] == pytest.approx(sum(probs[3:]), rel=1e-9, abs=1e-9)

    expected = _expected_posterior_from_prior(680, 2, 0, "GOGO3", gogo_pi)
    first = posterior.iloc[2]
    for i, value in enumerate(expected, start=1):
        assert first[f"p_set{i}"] == pytest.approx(value, rel=1e-9, abs=1e-9)

    expected = _expected_posterior_from_prior(1000, 3, 0, "MYV", hall_pi)
    first = posterior.iloc[0]
    for i, value in enumerate(expected, start=1):
        assert first[f"p_set{i}"] == pytest.approx(value, rel=1e-9, abs=1e-9)

    assert "Empirical prior" in summary
    assert "Prior Table" in summary
    assert "## Family RB Sanity (G-weighted rb/G)" in summary
    assert "machine 2026 excluded: N/A (no rows to exclude)" in summary
    assert "0707 excluded: N/A (no rows to exclude)" in summary
    assert "mean p_high:" in summary
    assert "approximate spec-consistency guard (0% to +5%)" in summary

    sanity = stage2._build_family_rb_sanity_table(posterior, prior_table)
    assert not sanity.empty
    assert {"within_5pct", "needs_review"} <= set(sanity.columns)
    assert bool(prior_table.loc[prior_table["family_key"].eq("GOGO3"), "converged"].iloc[0]) is True


def test_main_writes_requested_stage2_artifacts(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage2_daily_posterior as stage2

    db_path = tmp_path / "sample.db"
    _create_stage2_sample_db(db_path)
    output_dir = tmp_path / "out"

    exit_code = stage2.main(["--hall", "蒲田7", "--db-path", str(db_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "stage2_daily_posterior.csv").exists()
    assert (output_dir / "stage2_prior_table.csv").exists()
    assert (output_dir / "stage2_summary.md").exists()
