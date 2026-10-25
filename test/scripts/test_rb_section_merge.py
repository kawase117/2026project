"""朝のRB候補生成の失敗隔離と文書への差し込み。"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_morning_docs as morning  # noqa: E402


def test_rb_generation_failure_and_dry_run(tmp_path, monkeypatch):
    calls = []

    def fail(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=1, stderr="temporary error", stdout="")

    monkeypatch.setattr(morning.subprocess, "run", fail)
    assert morning.run_rb_candidates(tmp_path, "20261025", True) is False
    assert "--no-freeze" in calls[0]
    assert morning.run_rb_candidates(tmp_path, "20261025", False) is False
    assert "--no-freeze" not in calls[1]


def test_merge_appends_rb_after_juggler_even_with_rbauto(tmp_path, monkeypatch):
    day_dir = tmp_path / "day"
    day_dir.mkdir()
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / "20261025__mitoya__rbauto.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(morning, "REVIEWS", reviews)
    monkeypatch.setattr(morning, "PREDICTIONS", preds)
    monkeypatch.setattr(morning, "HALLS", {"mitoya": ("みとや大森町店", "みとや")})
    monkeypatch.setattr(morning, "juggler_section", lambda *_: "## ジャグラー候補\n\n候補表")
    (day_dir / "mitoya.prediction.done").write_text("done", encoding="utf-8")
    (day_dir / "mitoya.prediction.md").write_text("## みとや大森町店\n判断: F4", encoding="utf-8")
    (day_dir / "rb_candidates.md").write_text("## RB機種候補\n\n### みとや大森町店", encoding="utf-8")
    morning.merge(day_dir, "20261025", "20261024")
    text = (reviews / "2026-10-25-prediction.md").read_text(encoding="utf-8")
    assert text.index("## ジャグラー候補") < text.index("## RB機種候補")
