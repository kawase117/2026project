from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _build_synthetic_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2026-01-01", periods=120, freq="D")
    machines = [
        {
            "machine_number": 101,
            "machine_name": "alpha",
            "section": "A",
            "kakuban": 1,
            "machine_digit": 1,
            "row_group": 100,
            "cluster_boost": 150.0,
        },
        {
            "machine_number": 102,
            "machine_name": "beta",
            "section": "A",
            "kakuban": 2,
            "machine_digit": 2,
            "row_group": 100,
            "cluster_boost": 150.0,
        },
        {
            "machine_number": 201,
            "machine_name": "gamma",
            "section": "B",
            "kakuban": 1,
            "machine_digit": 1,
            "row_group": 200,
            "cluster_boost": -150.0,
        },
        {
            "machine_number": 202,
            "machine_name": "delta",
            "section": "B",
            "kakuban": 2,
            "machine_digit": 2,
            "row_group": 200,
            "cluster_boost": -150.0,
        },
    ]

    for date in dates:
        day_factor = (date.day % 5) * 10.0
        for machine in machines:
            residual_target = machine["cluster_boost"] + day_factor
            diff = residual_target * 3_000 + 400.0
            rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "machine_number": machine["machine_number"],
                    "machine_name": machine["machine_name"],
                    "games": 1000,
                    "diff": diff,
                    "section": machine["section"],
                    "kakuban": machine["kakuban"],
                    "machine_digit": machine["machine_digit"],
                    "row_group": machine["row_group"],
                }
            )
    return pd.DataFrame(rows)


def _build_sparse_pivot() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "101": [1.0, 2.0, 3.0, np.nan, np.nan],
            "102": [1.5, 2.5, 3.5, np.nan, np.nan],
            "201": [np.nan, np.nan, 7.0, 8.0, 9.0],
        },
        index=pd.Index(["20260101", "20260102", "20260103", "20260104", "20260105"], name="date"),
    )


def test_fixed_effect_residuals_remove_known_group_means() -> None:
    from ml.experiments.latent_grouping import residual_clustering as rc

    frame = _build_synthetic_rows()
    residuals = rc.compute_fixed_effect_residuals(frame)

    assert "residual_payout_rate" in residuals.columns
    for column in ["machine_name", "section", "kakuban", "machine_digit", "row_group"]:
        grouped_means = residuals.groupby(column)["residual_payout_rate"].mean().abs()
        assert grouped_means.max() < 1e-6


def test_sequential_demeaning_tracks_regression_residuals() -> None:
    from ml.experiments.latent_grouping import residual_clustering as rc

    frame = _build_synthetic_rows()
    regression = rc.compute_fixed_effect_residuals(frame)
    demeaned = rc.compute_sequential_demeaned_residuals(frame)

    merged = regression[["machine_number", "date", "residual_payout_rate"]].merge(
        demeaned[["machine_number", "date", "sequential_residual_payout_rate"]],
        on=["machine_number", "date"],
        how="inner",
    )
    corr = merged["residual_payout_rate"].corr(merged["sequential_residual_payout_rate"])
    assert corr > 0.9


def test_pairwise_correlations_respect_min_common_days() -> None:
    from ml.experiments.latent_grouping import residual_clustering as rc

    pivot = _build_sparse_pivot()
    corr, common_days = rc.compute_pairwise_correlations(pivot, min_common_days=3)

    assert common_days.loc[101, 102] == 3
    assert pytest.approx(corr.loc[101, 102], rel=1e-6) == 1.0
    assert common_days.loc[101, 201] == 1
    assert np.isnan(corr.loc[101, 201])


def test_cluster_assignment_and_report_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ml.experiments.latent_grouping import residual_clustering as rc

    output_dir = tmp_path / "results"
    hall = "蒲田7"
    raw = _build_synthetic_rows().loc[:, ["date", "machine_number", "machine_name", "games", "diff"]].copy()
    raw["hall"] = hall

    layout = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202],
            "rank_from_min": [1, 2, 1, 2],
            "section": ["A", "A", "B", "B"],
        }
    )

    monkeypatch.setattr(rc, "load_hall_df", lambda _hall: raw.copy())
    monkeypatch.setattr(
        rc,
        "_prepare_frame",
        lambda frame, *, shindai_exclude_days: frame.assign(payout_rate=rc._payout_rate(frame)),
    )
    monkeypatch.setattr(rc, "_load_hall_layout_frame", lambda *args, **kwargs: layout.copy())

    exit_code = rc.main(["--halls", hall, "--output-dir", str(output_dir)])

    assert exit_code == 0
    csv_path = output_dir / f"{hall}_residual_corr_clusters.csv"
    report_path = output_dir / f"{hall}_cluster_ari_report.md"
    assert csv_path.exists()
    assert report_path.exists()

    cluster_frame = pd.read_csv(csv_path, encoding="utf-8-sig")
    assert set(cluster_frame.columns) == {
        "machine_number",
        "machine_name",
        "section",
        "kakuban",
        "machine_digit",
        "row_group",
        "cluster_id",
    }
    assert cluster_frame["cluster_id"].nunique() == 2

    report_text = report_path.read_text(encoding="utf-8")
    assert "Adjusted Rand Index" in report_text
    assert "silhouette" in report_text.lower()


def test_main_does_not_resolve_mitoya_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ml.experiments.latent_grouping import residual_clustering as rc

    output_dir = tmp_path / "results"
    hall = "みとや"
    raw = _build_synthetic_rows().loc[:, ["date", "machine_number", "machine_name", "games", "diff"]].copy()
    raw["hall"] = hall

    layout = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202],
            "rank_from_min": [1, 2, 1, 2],
            "section": ["A", "A", "B", "B"],
        }
    )

    resolve_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    layout_calls: list[dict[str, object]] = []

    assert not hasattr(rc, "resolve_mitoya_db_path")
    monkeypatch.setattr(rc, "load_hall_df", lambda _hall: raw.copy())
    monkeypatch.setattr(
        rc,
        "_prepare_frame",
        lambda frame, *, shindai_exclude_days: frame.assign(payout_rate=rc._payout_rate(frame)),
    )

    def fake_load_hall_layout_frame(*args, **kwargs):
        layout_calls.append(kwargs.copy())
        return layout.copy()

    monkeypatch.setattr(rc, "_load_hall_layout_frame", fake_load_hall_layout_frame)

    exit_code = rc.main(["--halls", hall, "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert resolve_calls == []
    assert layout_calls and layout_calls[0]["mitoya_db_path"] is None
    assert (output_dir / f"{hall}_residual_corr_clusters.csv").exists()
    assert (output_dir / f"{hall}_cluster_ari_report.md").exists()


def test_main_with_real_mitoya_layout_stays_in_500_band(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ml.experiments.latent_grouping import residual_clustering as rc
    import eda.section_kakuban_axis_pattern_scan as hall_scan

    real_db = Path(__file__).resolve().parents[2] / "db" / "みとや大森町店.db"
    assert real_db.exists()

    with sqlite3.connect(real_db) as conn:
        layout = pd.read_sql_query(
            """
            SELECT machine_number, rank_from_min, section
            FROM machine_layout
            ORDER BY machine_number
            LIMIT 8
            """,
            conn,
        )

    machine_numbers = layout["machine_number"].astype(int).tolist()
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    rows: list[dict[str, object]] = []
    for date in dates:
        for idx, machine_number in enumerate(machine_numbers):
            rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "machine_number": machine_number,
                    "machine_name": f"machine_{idx % 4}",
                    "games": 1000,
                    "diff": (idx % 2) * 200 - 50,
                }
            )
    raw = pd.DataFrame(rows)

    resolve_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(rc, "load_hall_df", lambda _hall: raw.copy())
    monkeypatch.setattr(
        hall_scan, "resolve_mitoya_db_path", lambda *args, **kwargs: resolve_calls.append((args, kwargs))
    )

    output_dir = tmp_path / "results"
    exit_code = rc.main(["--halls", "みとや", "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert resolve_calls == []

    cluster_frame = pd.read_csv(output_dir / "みとや_residual_corr_clusters.csv", encoding="utf-8-sig")
    assert not cluster_frame.empty
    assert cluster_frame["machine_number"].min() >= 501
    assert cluster_frame["machine_number"].max() <= 815
    assert cluster_frame["machine_number"].astype(int).between(500, 999).all()
