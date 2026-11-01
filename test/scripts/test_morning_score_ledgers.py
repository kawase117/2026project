"""朝の答え合わせの前に、凍結済みの台帳を採点する。失敗しても止めず、dry-run では走らせない。"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_morning_docs as morning  # noqa: E402


def record_calls(monkeypatch, returncode=0, exc=None):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if exc:
            raise exc
        return SimpleNamespace(returncode=returncode, stdout="", stderr="boom")

    monkeypatch.setattr(morning.subprocess, "run", fake_run)
    return calls


def test_runs_both_score_due_once_each(monkeypatch):
    calls = record_calls(monkeypatch)
    morning.score_ledgers(False)
    assert [c[4:] for c in calls] == [
        ["backtest.prediction_ledger", "score-due"],
        ["backtest.forward", "score-due"],
    ]
    assert all(c[1:3] == ["-X", "utf8"] for c in calls)


def test_dry_run_does_not_run(monkeypatch):
    calls = record_calls(monkeypatch)
    morning.score_ledgers(True)
    assert calls == []


def test_failure_does_not_stop_or_raise(monkeypatch, capsys):
    calls = record_calls(monkeypatch, returncode=1)
    morning.score_ledgers(False)
    assert len(calls) == 2
    assert "台帳の採点失敗" in capsys.readouterr().out


def test_timeout_does_not_raise(monkeypatch, capsys):
    calls = record_calls(monkeypatch, exc=subprocess.TimeoutExpired("x", 1))
    morning.score_ledgers(False)
    assert len(calls) == 2
    assert "台帳の採点失敗" in capsys.readouterr().out
