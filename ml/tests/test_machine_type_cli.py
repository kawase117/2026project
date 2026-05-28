import subprocess
import sys

import pandas as pd


def test_machine_type_nextday_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ml.machine_type.machine_type_nextday", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "next-day" in result.stdout.lower() or "nextday" in result.stdout.lower()


def test_machine_type_monthly_check_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ml.machine_type.machine_type_monthly_check", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "monthly" in result.stdout.lower()


def test_machine_type_alpha_sensitivity_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ml.machine_type.machine_type_alpha_sensitivity", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "alpha" in result.stdout.lower()


def test_machine_type_nextday_module_has_parser() -> None:
    from ml.machine_type import machine_type_nextday

    parser = machine_type_nextday.build_parser()
    assert parser.prog
    assert "--prior-blend-weight" in parser.format_help()


def test_machine_type_monthly_check_module_has_parser() -> None:
    from ml.machine_type import machine_type_monthly_check

    parser = machine_type_monthly_check.build_parser()
    assert parser.prog
    assert "--prior-blend-weight" in parser.format_help()


def test_machine_type_alpha_sensitivity_module_has_parser() -> None:
    from ml.machine_type import machine_type_alpha_sensitivity

    parser = machine_type_alpha_sensitivity.build_parser()
    assert parser.prog


def test_floor_diversity_selector_keeps_both_floors_when_possible() -> None:
    from ml.machine_type.machine_type_nextday import _select_recommended_indices

    df = pd.DataFrame(
        {
            "nextday_rank": [1, 2, 3, 4],
            "segment_floor2": ["2F", "2F", "3F", "3F"],
        }
    )
    selected = _select_recommended_indices(df, k=2, enforce_floor_diversity=True)
    picked = df.loc[selected, "segment_floor2"].astype(str).tolist()
    assert "2F" in picked and "3F" in picked
