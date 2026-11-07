"""前日分が DB に無いホールでは答え合わせを作らない(2026-11-08 の ARROW: DB最終 11/6 で 11/7 の答え合わせを作った)。

予測の段は今まで通り回す。答え合わせの断片・完了印は作らず、後の起動で前日分が入ればそこで作る。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_morning_docs as morning  # noqa: E402

TODAY, YESTERDAY = "20261108", "20261107"


def stub_pipeline(monkeypatch, db_max: str) -> list[str]:
    """claude・DB・ジャグラー表を差し替え、generate が呼ばれた段の名前を返す。"""
    calls: list[str] = []
    monkeypatch.setattr(morning, "hall_max_dates", lambda: {"ARROW池上店": db_max})
    monkeypatch.setattr(morning, "announce_files", lambda key, day: [])
    monkeypatch.setattr(morning, "prediction_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(morning, "append_takoslot", lambda *a, **k: None)
    monkeypatch.setattr(morning, "day_facts", lambda *a, **k: {})
    monkeypatch.setattr(morning, "poster_lines", lambda *a, **k: [])
    monkeypatch.setattr(morning.result_check, "lines_for_facts", lambda *a, **k: [])
    monkeypatch.setattr(morning, "answercheck_prompt", lambda *a, **k: "prompt")

    def fake_juggler(key, out):
        out.write_text("jug", encoding="utf-8")
        return True

    def fake_generate(prompt, out, validate, label, **kwargs):
        calls.append(label)
        out.write_text("## %s\n本文" % label, encoding="utf-8")
        return True

    monkeypatch.setattr(morning, "run_juggler", fake_juggler)
    monkeypatch.setattr(morning, "generate", fake_generate)
    return calls


def test_lagged_hall_gets_no_answercheck_but_still_prediction(monkeypatch, tmp_path):
    calls = stub_pipeline(monkeypatch, db_max="20261106")
    morning.process_hall("arrow", tmp_path, YESTERDAY, TODAY, dry_run=False)

    assert "arrow 答え合わせ" not in calls
    assert not (tmp_path / "arrow.answercheck.md").exists()
    assert not (tmp_path / "arrow.answercheck.done").exists()
    assert "arrow 予測" in calls
    assert (tmp_path / "arrow.prediction.done").exists()


def test_lagged_hall_is_not_merged_into_answercheck_doc(monkeypatch, tmp_path):
    stub_pipeline(monkeypatch, db_max="20261106")
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    monkeypatch.setattr(morning, "REVIEWS", reviews)
    monkeypatch.setattr(morning, "PREDICTIONS", tmp_path / "preds")
    monkeypatch.setattr(morning, "HALLS", {"arrow": morning.HALLS["arrow"]})
    monkeypatch.setattr(morning, "watch_note", lambda *a, **k: "")
    monkeypatch.setattr(morning, "juggler_section", lambda *a, **k: "")
    monkeypatch.setattr(morning, "trial_section", lambda *a, **k: "")
    day_dir = tmp_path / TODAY
    day_dir.mkdir()

    morning.process_hall("arrow", day_dir, YESTERDAY, TODAY, dry_run=False)
    morning.merge(day_dir, TODAY, YESTERDAY)

    assert not (reviews / "2026-11-07-answercheck.md").exists()
    assert (reviews / "2026-11-08-prediction.md").exists()


def test_answercheck_made_later_once_yesterday_arrives(monkeypatch, tmp_path):
    stub_pipeline(monkeypatch, db_max="20261106")
    morning.process_hall("arrow", tmp_path, YESTERDAY, TODAY, dry_run=False)

    calls = stub_pipeline(monkeypatch, db_max="20261107")
    morning.process_hall("arrow", tmp_path, YESTERDAY, TODAY, dry_run=False)

    assert calls == ["arrow 答え合わせ"]  # 予測は済んでいるので作り直さない
    assert (tmp_path / "arrow.answercheck.done").exists()


def test_answercheck_ready_requires_yesterday_even_for_lagged_hall():
    assert morning.ready_day("arrow", YESTERDAY) <= "20261106"  # 予測の段は回す
    assert not morning.answercheck_ready("arrow", YESTERDAY, {"ARROW池上店": "20261106"})
    assert morning.answercheck_ready("arrow", YESTERDAY, {"ARROW池上店": "20261107"})
    assert not morning.answercheck_ready("arrow", YESTERDAY, {})
