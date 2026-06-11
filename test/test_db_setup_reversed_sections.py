from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = PROJECT_ROOT / "database"
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))

import db_setup  # noqa: E402


def test_load_reversed_sections_prefers_file_path(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    database_dir = project_root / "database"
    config_dir = project_root / "config"
    misleading_config_dir = database_dir / "config"
    config_dir.mkdir(parents=True)
    misleading_config_dir.mkdir(parents=True)

    valid_config = {
        "halls": [
            {
                "hall_name": "みとやスロス",
                "layout_settings": {"reversed_sections": ["692-711", "557-590"]},
            }
        ]
    }
    (config_dir / "hall_config.json").write_text(
        json.dumps(valid_config, ensure_ascii=False),
        encoding="utf-8",
    )
    (misleading_config_dir / "hall_config.json").write_text(
        json.dumps({"halls": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        db_setup,
        "__file__",
        str(database_dir / "db_setup.py"),
        raising=False,
    )
    monkeypatch.chdir(database_dir)

    result = db_setup._load_reversed_sections("みとやスロス", "db")

    assert result == frozenset({"692-711", "557-590"})

