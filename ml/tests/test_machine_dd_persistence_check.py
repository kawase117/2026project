from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _make_row(
    date: str,
    machine_number: int,
    machine_name: str,
    diff: float,
    *,
    games: int = 1000,
) -> dict[str, object]:
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "diff": diff,
        "games": games,
    }


def _make_candidate_rows(hall: str, machine_name: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "hall": hall,
                "machine_name": machine_name,
                "axis": "dd",
                "outcome": "plus",
                "effect_size": 0.2,
                "n_obs": 100,
            },
            {
                "hall": hall,
                "machine_name": machine_name,
                "axis": "dd",
                "outcome": "hit104",
                "effect_size": 0.18,
                "n_obs": 100,
            },
        ]
    )


def _write_candidate_file(path: Path, hall: str, machine_name: str) -> None:
    frame = _make_candidate_rows(hall, machine_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _make_balanced_frame(machine_name: str, *, reverse: bool = False) -> pd.DataFrame:
    dd_order = list(range(1, 11))
    if reverse:
        dd_order_b = list(reversed(dd_order))
    else:
        dd_order_b = dd_order.copy()
    dd_order_a = dd_order.copy()

    rows: list[dict[str, object]] = []
    category_patterns = {
        0: [180, 160, 140],
        1: [150, 130, 110],
        2: [90, 70, -10],
        3: [-20, -30, -40],
    }
    months_a = [1, 2, 3]
    months_b = [4, 5, 6]
    machine_number = 1000 if machine_name == "stable" else 2000

    def _emit(months: list[int], dd_values: list[int], flipped: bool) -> None:
        for month in months:
            for idx, dd in enumerate(dd_values):
                category = idx % 4
                if flipped:
                    category = 3 - category
                diffs = category_patterns[category]
                rows.append(_make_row(f"2026{month:02d}{dd:02d}", machine_number, machine_name, diffs[idx % 3]))

    _emit(months_a, dd_order_a, False)
    _emit(months_b, dd_order_b, reverse)
    return pd.DataFrame(rows)


def _make_small_frame(machine_name: str) -> pd.DataFrame:
    rows = [
        _make_row("20260101", 1001, machine_name, 150),
        _make_row("20260201", 1001, machine_name, 140),
        _make_row("20260302", 1001, machine_name, -20),
        _make_row("20260402", 1001, machine_name, -30),
    ]
    return pd.DataFrame(rows)


def _make_sparse_frame(machine_name: str) -> pd.DataFrame:
    rows = [
        _make_row("20260101", 1002, machine_name, 160),
        _make_row("20260201", 1002, machine_name, 140),
        _make_row("20260302", 1002, machine_name, -20),
        _make_row("20260402", 1002, machine_name, -30),
        _make_row("20260503", 1002, machine_name, 80),
        _make_row("20260603", 1002, machine_name, 70),
    ]
    return pd.DataFrame(rows)


def test_build_hall_outputs_finds_positive_and_negative_persistence() -> None:
    from eda import machine_dd_persistence_check as analysis

    stable_frame = _make_balanced_frame("stable", reverse=False)
    flip_frame = _make_balanced_frame("flip", reverse=True)
    raw = pd.concat([stable_frame, flip_frame], ignore_index=True)
    candidates = pd.concat(
        [
            _make_candidate_rows("蒲田1", "stable"),
            _make_candidate_rows("蒲田1", "flip"),
        ],
        ignore_index=True,
    )

    result = analysis.build_hall_outputs(
        "蒲田1",
        raw,
        candidate_signals=candidates,
        shindai_exclude_days=0,
        currently_installed_grace_days=0,
        min_machine_days_for_split=10,
        min_cell_n_for_split=1,
        min_common_levels=10,
    )

    stable_row = result.loc[result["machine_name"].eq("stable") & result["outcome"].eq("plus")].iloc[0]
    flip_row = result.loc[result["machine_name"].eq("flip") & result["outcome"].eq("plus")].iloc[0]
    assert stable_row["spearman_rho"] >= 0.7
    assert flip_row["spearman_rho"] <= 0.3


def test_build_hall_outputs_skips_short_machine_and_sparse_levels() -> None:
    from eda import machine_dd_persistence_check as analysis

    short_result = analysis.build_hall_outputs(
        "蒲田1",
        _make_small_frame("short"),
        candidate_signals=_make_candidate_rows("蒲田1", "short"),
        shindai_exclude_days=0,
        currently_installed_grace_days=0,
        min_machine_days_for_split=10,
        min_cell_n_for_split=1,
        min_common_levels=3,
    )
    short_row = short_result.iloc[0]
    assert "min_machine_days_for_split" in str(short_row["note"])
    assert pd.isna(short_row["spearman_rho"])

    sparse_result = analysis.build_hall_outputs(
        "蒲田1",
        _make_sparse_frame("sparse"),
        candidate_signals=_make_candidate_rows("蒲田1", "sparse"),
        shindai_exclude_days=0,
        currently_installed_grace_days=0,
        min_machine_days_for_split=1,
        min_cell_n_for_split=3,
        min_common_levels=5,
    )
    sparse_row = sparse_result.iloc[0]
    assert "n_common_dd_levels" in str(sparse_row["note"])
    assert pd.isna(sparse_row["spearman_rho"])


def test_main_writes_persistence_check_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import machine_dd_persistence_check as analysis

    raw = _make_balanced_frame("stable", reverse=False)
    candidate_dir = tmp_path / "signals"
    output_path = tmp_path / "out" / "persistence_check.csv"
    _write_candidate_file(candidate_dir / "蒲田1_top_signals.csv", "蒲田1", "stable")

    monkeypatch.setattr(analysis, "DEFAULT_SIGNAL_DIR", candidate_dir)
    monkeypatch.setattr(analysis, "DEFAULT_OUTPUT_PATH", output_path)
    monkeypatch.setattr(analysis, "HALL_DBS", {"蒲田1": "fake.db"})
    monkeypatch.setattr(analysis, "load_hall_df", lambda hall: raw)

    exit_code = analysis.main(
        [
            "--halls",
            "蒲田1",
            "--min-machine-days-for-split",
            "10",
            "--min-cell-n-for-split",
            "1",
            "--min-common-levels",
            "5",
        ]
    )

    assert exit_code == 0
    assert output_path.exists()
    written = pd.read_csv(output_path)
    assert set(["hall", "machine_name", "outcome", "spearman_rho"]).issubset(written.columns)
    assert not written.empty
