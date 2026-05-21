import subprocess
import sys


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


def test_machine_type_nextday_module_has_parser() -> None:
    from ml.machine_type import machine_type_nextday

    parser = machine_type_nextday.build_parser()
    assert parser.prog


def test_machine_type_monthly_check_module_has_parser() -> None:
    from ml.machine_type import machine_type_monthly_check

    parser = machine_type_monthly_check.build_parser()
    assert parser.prog

