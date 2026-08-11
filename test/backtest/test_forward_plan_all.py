"""plan-all（全ルール機械的凍結）の欠測記録が守られているかの検証。

フォワードテストの証拠価値は「負けそうな日を飛ばしていない」ことに依存する。
plan が存在しない (rule_id, date) について、その不在が
「エントリー日ではなかった」「履歴不足で落ちた」「既に凍結済み」の
どれなのかが RUNS.jsonl から常に復元できることを担保する。

戻り値ではなく **永続化された RUNS.jsonl の中身** を検証する。
plan_all() が正しい dict を返しても、書き出しに落ちがあれば証拠は残らない。

DB には触らない。plan() をスタブに差し替え、分岐と記録だけを見る。
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from backtest import forward
from backtest.prereg import PreRegistration

JST = timezone(timedelta(hours=9))


def _reg(rule_id: str, *, score: str = "hist_mean_diff", entry_days: dict | None = None) -> PreRegistration:
    return PreRegistration(
        rule_id=rule_id,
        hall="テストホール",
        hypothesis="テスト用",
        source_instinct="none",
        eval_start="20260101",
        eval_end="20261231",
        success_criterion="テスト用",
        universe={"jug_flag": 1},
        eligibility={"last_digit": ["7"]},
        entry_days=entry_days or {},
        score=score,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    """FORWARD_DIR / LEDGER / RUNS_LEDGER を一時ディレクトリに逃がす。"""
    monkeypatch.setattr(forward, "FORWARD_DIR", tmp_path)
    monkeypatch.setattr(forward, "LEDGER", tmp_path / "LEDGER.jsonl")
    monkeypatch.setattr(forward, "RUNS_LEDGER", tmp_path / "RUNS.jsonl")
    return tmp_path


def _runs(env) -> list[dict]:
    """永続化された実行記録を読む。"""
    path = env / "RUNS.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _stub_plan(regs_ok: set[str], boom: dict[str, Exception] | None = None):
    def _plan(reg, target_date, allow_past=False):
        if boom and reg.rule_id in boom:
            raise boom[reg.rule_id]
        if reg.rule_id not in regs_ok:
            raise ValueError("min_history_days を満たす台がない")
        return {
            "rule_id": reg.rule_id,
            "hall": reg.hall,
            "freeze_hash": reg.freeze_hash(),
            "target_date": target_date,
            "data_asof": "20260810",
            "picks": [{"machine_number": 1111, "machine_name": "x", "score": 1.0, "history_days": 9}],
            "result": None,
        }

    return _plan


def test_every_rule_gets_a_persisted_disposition(env, monkeypatch):
    regs = [
        _reg("ok_rule"),
        _reg("broken_rule"),
        _reg("filter_only_rule", score="none"),
        _reg("wrong_day_rule", entry_days={"dd": [7, 17, 27]}),
    ]
    monkeypatch.setattr(forward, "load_preregs", lambda: regs)
    monkeypatch.setattr(forward, "plan", _stub_plan({"ok_rule"}))

    forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))

    (rec,) = _runs(env)  # 永続化された記録そのものを見る
    got = {d["rule_id"]: d["status"] for d in rec["dispositions"]}
    assert got == {
        "ok_rule": "planned",
        "broken_rule": "failed",
        "filter_only_rule": "skipped_no_score",
        "wrong_day_rule": "skipped_not_entry_day",
    }
    # 全ルールが必ず1件ずつ現れる。黙って消えるルールがあってはならない。
    assert rec["n_rules"] == len(regs) == len(rec["dispositions"])
    assert rec["counts"] == {
        "failed": 1,
        "planned": 1,
        "skipped_no_score": 1,
        "skipped_not_entry_day": 1,
    }
    # 凍結できなかったルールがあるので "ok" にはならない
    assert rec["run_status"] == "incomplete"
    # 落ちた理由が後から読める（「なぜ plan が無いのか」に答えられる）
    failed = next(d for d in rec["dispositions"] if d["status"] == "failed")
    assert "min_history_days" in failed["error"]


def test_plan_all_has_no_rule_subset_argument():
    """部分実行できると「全ルール回した」記録を偽装できてしまう。

    ルールを絞る引数は存在してはならない（Codex レビュー CRITICAL-1）。
    """
    assert set(inspect.signature(forward.plan_all).parameters) == {
        "target_date",
        "allow_past",
        "now",
    }


def test_run_record_is_appended_not_overwritten(env, monkeypatch):
    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("ok_rule")])
    monkeypatch.setattr(forward, "plan", _stub_plan({"ok_rule"}))

    forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))
    # 2回目。既に凍結済みなので plan は作り直されない。
    forward.plan_all("20260812", now=datetime(2026, 8, 11, 22, 0, tzinfo=JST))

    recs = _runs(env)
    assert len(recs) == 2, "実行記録は追記専用でなければならない"
    assert recs[0]["counts"] == {"planned": 1}
    assert recs[1]["dispositions"][0]["status"] == "already_frozen"
    # 台帳側は二重登録されない
    ledger = (env / "LEDGER.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(ledger) == 1


def test_orphaned_plan_is_not_reported_as_frozen(env, monkeypatch):
    """plan ファイルはあるが台帳に無い状態を already_frozen にしてはならない。

    この状態の plan は score() が採点を拒否するので、素通りさせると
    その (ルール, 日) は静かに欠測として確定する。
    """
    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("ok_rule")])
    monkeypatch.setattr(forward, "plan", _stub_plan({"ok_rule"}))

    # 台帳追記だけが失敗した状況を再現する（plan JSON は書けている）
    real_append = forward._append_ledger
    calls = {"n": 0}

    def _flaky_append(plan_obj, note=""):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("ledger write failed")
        return real_append(plan_obj, note)

    monkeypatch.setattr(forward, "_append_ledger", _flaky_append)

    with pytest.raises(OSError):
        forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))
    assert (env / "ok_rule__20260812.json").exists()
    assert _runs(env)[0]["run_status"] == "fatal", "台帳書き込み失敗は想定内エラーではない"

    # 台帳追記が復旧した後に再実行しても「凍結済み」で素通りしない
    forward.plan_all("20260812", now=datetime(2026, 8, 11, 22, 0, tzinfo=JST))

    recs = _runs(env)
    assert recs[-1]["dispositions"][0]["status"] == "orphaned_plan"
    assert recs[-1]["run_status"] == "incomplete"


def test_unexpected_exception_is_recorded_then_raised(env, monkeypatch):
    """DB 障害等は failed に紛れさせず、記録したうえで送出する。"""
    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("a_rule"), _reg("b_rule")])
    monkeypatch.setattr(
        forward,
        "plan",
        _stub_plan({"a_rule", "b_rule"}, boom={"a_rule": RuntimeError("db is down")}),
    )

    with pytest.raises(RuntimeError, match="db is down"):
        forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))

    (rec,) = _runs(env)
    assert rec["run_status"] == "fatal"
    assert rec["dispositions"][0]["status"] == "fatal"
    assert "db is down" in rec["fatal_error"]


def test_prereg_load_failure_still_leaves_a_run_record(env, monkeypatch):
    """事前登録が壊れている日を「実行しなかった日」と混同させない。"""

    def _boom():
        raise ValueError("prereg is corrupt")

    monkeypatch.setattr(forward, "load_preregs", _boom)
    with pytest.raises(ValueError, match="prereg is corrupt"):
        forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))

    (rec,) = _runs(env)
    assert rec["run_status"] == "fatal"
    assert rec["n_rules"] == 0
    assert "prereg is corrupt" in rec["fatal_error"]


def test_freeze_plan_never_overwrites(env, monkeypatch):
    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("ok_rule")])
    monkeypatch.setattr(forward, "plan", _stub_plan({"ok_rule"}))
    forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))

    frozen = (env / "ok_rule__20260812.json").read_text(encoding="utf-8")
    obj = json.loads(frozen)
    obj["picks"] = [{"machine_number": 9999}]
    with pytest.raises(FileExistsError):
        forward._freeze_plan(obj)
    assert (env / "ok_rule__20260812.json").read_text(encoding="utf-8") == frozen


def test_late_wallclock_is_flagged(env, monkeypatch):
    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("ok_rule")])
    monkeypatch.setattr(forward, "plan", _stub_plan({"ok_rule"}))

    forward.plan_all("20260812", now=datetime(2026, 8, 11, 23, 59, tzinfo=JST))
    forward.plan_all("20260813", now=datetime(2026, 8, 13, 0, 1, tzinfo=JST))

    recs = _runs(env)
    assert recs[0]["is_late_wallclock"] is False
    assert recs[1]["is_late_wallclock"] is True, "対象日の0時を過ぎたら事前凍結ではない"


def test_late_wallclock_uses_jst_regardless_of_host_timezone():
    """ホストが UTC でも JST 0 時が境界であること。"""
    utc = timezone.utc
    # 2026-08-11 15:30 UTC = 2026-08-12 00:30 JST → 対象日 08-12 は既に始まっている
    assert forward.is_late_wallclock("20260812", datetime(2026, 8, 11, 15, 30, tzinfo=utc)) is True
    # 2026-08-11 14:30 UTC = 2026-08-11 23:30 JST → まだ前日
    assert forward.is_late_wallclock("20260812", datetime(2026, 8, 11, 14, 30, tzinfo=utc)) is False


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="タイムゾーン付き"):
        forward.is_late_wallclock("20260812", datetime(2026, 8, 11, 21, 0))


@pytest.mark.parametrize("bad", ["2026-08-12", "202608", "20261301", "", "20260812 "])
def test_parse_date_rejects_non_yyyymmdd(bad):
    with pytest.raises(ValueError):
        forward.parse_date(bad)


def test_audit_flags_days_with_no_run_record(env, monkeypatch):
    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("ok_rule"), _reg("broken_rule")])
    monkeypatch.setattr(forward, "plan", _stub_plan({"ok_rule"}))

    forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))

    rep = forward.audit("20260811", "20260813")
    by_date = {d["date"]: d for d in rep["days"]}
    assert by_date["20260811"]["status"] == "no_run_record"
    assert by_date["20260813"]["status"] == "no_run_record"
    # 実行した日は全ルールを網羅しているが、凍結に失敗したルールがある
    assert by_date["20260812"]["status"] == "has_problem_rules"
    assert by_date["20260812"]["problem_rules"] == ["broken_rule"]
    assert rep["n_registered_rules"] == 2


def test_audit_detects_uncovered_rule(env, monkeypatch):
    """ルールを増やした後、過去の実行記録がそれを含まないことを検出できる。"""
    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("ok_rule")])
    monkeypatch.setattr(forward, "plan", _stub_plan({"ok_rule"}))
    forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))

    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("ok_rule"), _reg("new_rule")])
    rep = forward.audit("20260812", "20260812")
    assert rep["days"][0]["status"] == "incomplete_coverage"
    assert rep["days"][0]["uncovered_rules"] == ["new_rule"]


def test_audit_counts_corrupt_lines(env, monkeypatch):
    monkeypatch.setattr(forward, "load_preregs", lambda: [_reg("ok_rule")])
    monkeypatch.setattr(forward, "plan", _stub_plan({"ok_rule"}))
    forward.plan_all("20260812", now=datetime(2026, 8, 11, 21, 0, tzinfo=JST))
    # 追記の途中で落ちた行を模す
    with (env / "RUNS.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"target_date": "202608\n')

    rep = forward.audit("20260812", "20260812")
    assert rep["corrupt_lines"] == 1


def test_load_preregs_reads_all_real_rules():
    """claims.json のような付随ファイルだけが除外され、ルールは全件読める。"""
    regs = forward.load_preregs()
    ids = {r.rule_id for r in regs}
    assert "k7_jug_rb_top3" in ids
    assert len(ids) == len(regs), "rule_id が重複している"
    on_disk = {p.stem for p in forward.PREREG_DIR.glob("*.json")}
    assert ids == on_disk - {"claims"}


def test_load_preregs_rejects_filename_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(forward, "PREREG_DIR", tmp_path)
    _reg("real_id").save(tmp_path / "different_name.json")
    with pytest.raises(ValueError, match="ファイル名と rule_id が不一致"):
        forward.load_preregs()
