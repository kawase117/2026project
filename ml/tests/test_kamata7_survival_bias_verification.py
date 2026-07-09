from __future__ import annotations

from pathlib import Path

import pandas as pd

import eda.kamata7_survival_bias_verification as survival


def _build_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add_machine(
        machine_name: str,
        machine_number: int,
        floor: str,
        seg: str,
        debut_days: list[int],
        diffs: list[int],
        *,
        is_any_event_days: set[int] | None = None,
    ) -> None:
        is_any_event_days = is_any_event_days or set()
        base = pd.Timestamp("2025-01-01")
        for day, diff in zip(debut_days, diffs, strict=True):
            date = base + pd.Timedelta(days=day)
            dd = int(date.strftime("%d"))
            rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "machine_name": machine_name,
                    "machine_number": machine_number,
                    "diff": diff,
                    "games": 1800,
                    "days_since_debut": day,
                    "pre_existing": False,
                    "floor": floor,
                    "seg": seg,
                    "section": f"{floor}_S",
                    "is_any_event": 1 if day in is_any_event_days or dd in {1, 7, 11, 17, 21, 22, 27, 31} else 0,
                }
            )

    add_machine(
        "survivor_a",
        2001,
        "2F",
        "N",
        [0, 10, 20, 30, 40, 50, 60, 70, 181],
        [80, 90, 100, 110, 120, 130, 140, 150, 160],
        is_any_event_days={10, 20, 30, 40, 50},
    )
    add_machine(
        "removed_b",
        2002,
        "2F",
        "N",
        [0, 10, 20, 30, 40, 50, 90, 120],
        [-120, -118, -116, -114, -112, -110, -90, -80],
        is_any_event_days={10, 20, 30, 40, 50},
    )
    add_machine(
        "censored_c",
        2003,
        "2F",
        "N",
        [0, 10, 20, 30, 40, 50, 330],
        [40, 45, 50, 55, 60, 65, 70],
        is_any_event_days={10, 20, 30, 40, 50, 330},
    )
    add_machine(
        "survivor_d",
        3001,
        "3F",
        "A",
        [0, 10, 20, 30, 40, 50, 60, 70, 270],
        [10, 20, 30, 40, 50, 60, 70, 80, 90],
        is_any_event_days={10, 20, 30, 40, 50},
    )
    add_machine(
        "removed_e",
        3002,
        "3F",
        "A",
        [0, 10, 20, 30, 40, 50, 90],
        [-30, -28, -26, -24, -22, -20, -10],
        is_any_event_days={10, 20, 30, 40, 50},
    )
    return pd.DataFrame(rows)


def test_step1_marks_censored_and_excludes_it_from_comparison() -> None:
    frame = _build_frame()
    labeled = survival._assign_survival_status(frame)
    step1 = survival._step1_survival_groups(labeled)

    assert set(labeled["survival_status"].unique()) == {"survived", "removed", "censored"}
    assert set(step1["group"].unique()) == {"survived", "removed", "censored"}

    censored_row = step1[(step1["segment"] == "2F_N") & (step1["group"] == "censored")].iloc[0]
    assert censored_row["n_machines"] == 1
    assert censored_row["debut_n"] == 5

    comparison = survival._comparison_subset(labeled)
    assert set(comparison["survival_status"].unique()) == {"survived", "removed"}


def test_step2_mwu_returns_survived_vs_removed_gap() -> None:
    frame = _build_frame()
    labeled = survival._assign_survival_status(frame)

    step2 = survival._step2_mwu(labeled)

    row = step2[step2["segment"] == "2F_N"].iloc[0]
    assert row["n_survived"] == 6
    assert row["n_removed"] == 5
    assert row["survived_debut_avg"] > row["removed_debut_avg"]
    assert row["p_value"] <= 1


def test_step5_floor_comparison_is_labeled_as_supplementary() -> None:
    frame = _build_frame()
    labeled = survival._assign_survival_status(frame)

    step5 = survival._step5_floor_comparison(labeled)

    assert list(step5["floor_type"]) == ["2F_N", "3F_A"]
    assert "floor差とA/N構成差の混入" in survival.build_report([], {"step5_floor_comparison.csv": step5})


def test_report_creates_files(tmp_path: Path) -> None:
    frame = _build_frame()
    labeled = survival._assign_survival_status(frame)
    metrics, outputs = survival.run_analysis(labeled)

    report_path = survival.write_artifacts(tmp_path, metrics, outputs)

    assert report_path.exists()
    assert (tmp_path / "step1_survival_groups.csv").exists()
    assert (tmp_path / "step2_mwu.csv").exists()
    assert (tmp_path / "step3_cohort_tracking.csv").exists()
    assert (tmp_path / "step4_event_debut_premium.csv").exists()
    assert (tmp_path / "step5_floor_comparison.csv").exists()
