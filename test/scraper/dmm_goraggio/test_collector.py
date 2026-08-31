import json
import tempfile
from pathlib import Path

from scraper.dmm_goraggio.collector import load_prior


def test_full_cache_is_preferred_even_when_quick_is_newer() -> None:
    with tempfile.TemporaryDirectory() as directory:
        temp_path = Path(directory)
        full = temp_path / "latest_full.json"
        quick = temp_path / "latest_quick.json"
        full.write_text(json.dumps({"mode": "full", "details": {"1001": {}}}), encoding="utf-8")
        quick.write_text(json.dumps({"mode": "quick", "details": {}}), encoding="utf-8")
        assert load_prior(temp_path, "full")["mode"] == "full"
