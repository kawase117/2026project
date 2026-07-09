from __future__ import annotations

from datetime import date

import pytest

from ml.experiments.walkforward_scoring import predict_daily as pdaily


def test_resolve_target_date_defaults_to_yesterday() -> None:
    assert pdaily.resolve_target_date(None, today=date(2026, 6, 26)) == "20260625"


def test_run_scraper_refuses_without_cli_support() -> None:
    with pytest.raises(pdaily.PipelineError, match="skip-scrape"):
        pdaily.run_scraper("20260625", "マルハンメガシティ2000-蒲田7")


def test_main_skips_existing_json_and_db_and_runs_predict(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[str] = []

    monkeypatch.setattr(pdaily, "resolve_target_date", lambda date_arg, today=None: "20260625")
    monkeypatch.setattr(pdaily, "resolve_hall_name", lambda hall_arg: "マルハンメガシティ2000-蒲田7")
    monkeypatch.setattr(
        pdaily,
        "json_path_for",
        lambda hall_name, date_str: tmp_path / "data" / hall_name / f"{date_str}_{hall_name}_data.json",
    )
    monkeypatch.setattr(pdaily, "_json_exists", lambda path: True)
    monkeypatch.setattr(pdaily, "db_path_for_hall", lambda hall_name: tmp_path / "db" / f"{hall_name}.db")
    monkeypatch.setattr(pdaily, "_db_has_date", lambda db_path, date_str: True)
    monkeypatch.setattr(pdaily, "run_scraper", lambda *args, **kwargs: calls.append("scrape"))
    monkeypatch.setattr(pdaily, "run_db_update", lambda *args, **kwargs: calls.append("db"))
    monkeypatch.setattr(pdaily, "run_predict_gated", lambda *args, **kwargs: calls.append("predict") or 0)

    exit_code = pdaily.main(["--skip-scrape", "--skip-db"])

    assert exit_code == 0
    assert calls == ["predict"]


def test_main_requires_json_when_skip_scrape(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(pdaily, "resolve_target_date", lambda date_arg, today=None: "20260625")
    monkeypatch.setattr(pdaily, "resolve_hall_name", lambda hall_arg: "マルハンメガシティ2000-蒲田7")
    monkeypatch.setattr(
        pdaily,
        "json_path_for",
        lambda hall_name, date_str: tmp_path / "data" / hall_name / f"{date_str}_{hall_name}_data.json",
    )
    monkeypatch.setattr(pdaily, "_json_exists", lambda path: False)
    monkeypatch.setattr(pdaily, "db_path_for_hall", lambda hall_name: tmp_path / "db" / f"{hall_name}.db")
    monkeypatch.setattr(pdaily, "_db_has_date", lambda db_path, date_str: True)
    monkeypatch.setattr(pdaily, "run_scraper", lambda *args, **kwargs: pytest.fail("scraper should not run"))
    monkeypatch.setattr(pdaily, "run_db_update", lambda *args, **kwargs: pytest.fail("db updater should not run"))
    monkeypatch.setattr(pdaily, "run_predict_gated", lambda *args, **kwargs: pytest.fail("predict should not run"))

    exit_code = pdaily.main(["--skip-scrape", "--skip-db"])

    assert exit_code == 1
