"""答え合わせの照合表(機械)と、本文の数字の検証。"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import answercheck_table as at  # noqa: E402

DAY = "20261031"
JUG = "マイジャグラーV"  # RB判別可能な機種(bonus_specs の judgeable)


def make_env(tmp_path, picks=None):
    """機種A1..A9(各3台、平均差枚 A_i = 100*i-500)、2台だけのSMALL、RB判別機 JUG(4台)。

    JUG は過去25日(1/300)に比べて当日だけ2倍のRB。G数は全機種4000でG比は1。
    """
    db = tmp_path / "hall.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INT, machine_name TEXT, "
        "games_normalized REAL, diff_coins_normalized REAL, rb_count REAL)"
    )
    rows = []
    target = datetime.strptime(DAY, "%Y%m%d")
    for back in range(1, 26):
        day = (target - timedelta(days=back)).strftime("%Y%m%d")
        for unit in range(4):
            rows.append((day, 9000 + unit, JUG, 6000, 0, 20))
    number = 1
    for i in range(1, 10):
        for _ in range(3):
            rows.append((DAY, number, "機種A%d" % i, 4000, 100 * i - 500, None))
            number += 1
    for _ in range(2):
        rows.append((DAY, number, "SMALL", 4000, 3000, None))
        number += 1
    for unit in range(4):
        rows.append((DAY, 9000 + unit, JUG, 4000, 0, 40))
    con.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    pred = tmp_path / "pred"
    pred.mkdir()
    (tmp_path / "announce").mkdir()
    base = {"models": [], "avoid_models": [], "units": [], "jug_units": []}
    base.update(picks or {})
    (pred / f"{DAY}__kamata7.json").write_text(json.dumps({"picks": base}), encoding="utf-8")
    return db, pred, tmp_path / "announce"


def build(tmp_path, picks):
    db, pred, ann = make_env(tmp_path, picks)
    return at.build_check_table(db, pred, ann, "kamata7", "kamata7", DAY)


def row(table, name):
    return next(r for r in table.rows if r.name == name)


def test_table_values_and_verdicts(tmp_path):
    table = build(tmp_path, {"models": ["機種A9", "機種A5", "機種A1"], "avoid_models": ["機種A2"]})
    top, mid, low = row(table, "機種A9"), row(table, "機種A5"), row(table, "機種A1")
    assert (top.n, round(top.mean), top.rank, top.total) == (3, 400, 1, 10)
    assert top.win == 1.0
    assert (top.verdict, top.result) == ("確かに強い", "当たり")
    assert (mid.verdict, mid.result) == ("平ら", "平ら")
    assert (low.verdict, low.result) == ("弱い", "外れ")
    assert "10機種中1位" in table.text and "+400" in table.text


def test_g_ratio_is_model_avg_over_hall_avg(tmp_path):
    table = build(tmp_path, {"models": ["機種A9"]})
    assert round(row(table, "機種A9").g_ratio, 2) == 1.0


def test_avoid_is_inverted(tmp_path):
    table = build(tmp_path, {"avoid_models": ["機種A1", "機種A9"]})
    assert row(table, "機種A1").result == "当たり"  # 避けて正解
    assert row(table, "機種A9").result == "外れ"  # 避けて外した


def test_rb_ratio_and_z(tmp_path):
    table = build(tmp_path, {"models": [JUG]})
    r = row(table, JUG)
    assert r.ratio == pytest.approx(3.0, abs=0.01)  # 当日 1/100、通常日 1/300
    assert r.z > at.STRONG_Z and r.verdict == "確かに強い"  # 順位は中位でも z>3 なら強い
    assert round(r.base_prob) == 300 and round(r.rb_prob) == 100


def test_small_sample_is_not_judged(tmp_path):
    table = build(tmp_path, {"models": ["SMALL"]})
    r = row(table, "SMALL")
    assert (r.verdict, r.result, r.mean) == ("標本小", "判定なし", None)
    assert len(table.small_units) == 2
    assert all((u.rank, u.total, u.verdict, u.result) == (1, 33, "確かに強い", "当たり") for u in table.small_units)
    assert "少台数の推し" in table.text
    assert at.check_table_numbers("SMALLの台28は4,000G・+3,000枚", table) == ([], [])


def test_small_unit_history_uses_only_prior_90_days(tmp_path):
    db, pred, ann = make_env(tmp_path, {"models": ["SMALL"]})
    target = datetime.strptime(DAY, "%Y%m%d")
    with sqlite3.connect(db) as con:
        con.executemany(
            "INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?)",
            [
                ((target - timedelta(days=back)).strftime("%Y%m%d"), 28, "SMALL", games, diff, None)
                for back, games, diff in ((1, 2000, 1000), (90, 6000, -500), (91, 10000, 9000))
            ],
        )
    table = at.build_check_table(db, pred, ann, "kamata7", "kamata7", DAY)
    assert all((u.hist_mean, u.hist_games, u.hist_days) == (250, 4000, 2) for u in table.small_units)


def test_small_unit_weak_and_scope(tmp_path):
    db, pred, ann = make_env(tmp_path, {"models": ["WEAK", "機種A9"], "avoid_models": ["SMALL"]})
    with sqlite3.connect(db) as con:
        con.executemany(
            "INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?)",
            [(DAY, number, "WEAK", 8000, -3000, None) for number in (50, 51)],
        )
    table = at.build_check_table(db, pred, ann, "kamata7", "kamata7", DAY)
    assert len(table.small_units) == 2
    assert {u.name for u in table.small_units} == {"WEAK"}
    assert all((u.verdict, u.result) == ("弱い", "外れ") for u in table.small_units)


def test_large_pick_and_small_avoid_have_no_small_units(tmp_path):
    table = build(tmp_path, {"models": ["機種A9"], "avoid_models": ["SMALL"]})
    assert table.small_units == []


def test_extra_strong_models_are_listed(tmp_path):
    table = build(tmp_path, {"models": ["機種A5"]})
    extras = [r.name for r in table.rows if r.group == at.GROUP_EXTRA]
    assert "機種A9" in extras and "機種A5" not in extras


@pytest.mark.parametrize(
    "rank,total,z,expected",
    [
        (1, 10, 0.0, "確かに強い"),
        (2, 10, 0.0, "平ら"),
        (5, 10, 3.0, "平ら"),  # z>3 は厳密な不等号
        (5, 10, 3.01, "確かに強い"),
        (10, 10, 0.0, "弱い"),
        (5, 10, -3.5, "弱い"),
        (1, 10, -3.5, "判定保留"),  # 順位は上位、zは大幅に負
        (7, 66, 0.0, "確かに強い"),  # 66機種の上位1割は7位まで
        (8, 66, 0.0, "平ら"),
    ],
)
def test_judge_thresholds(rank, total, z, expected):
    assert at.judge(rank, total, z) == expected


def test_units_table(tmp_path):
    table = build(tmp_path, {"jug_units": [9000, 1, 77777]})
    by_number = {u.number: u for u in table.units}
    assert by_number[9000].verdict == "確かに強い"
    assert by_number[1].verdict in ("回転不足", "判別不可")  # 4000G・RB無しの機種
    assert by_number[77777].verdict == "データ無し"


# ---------------------------------------------------------------- 本文の数字の検証


@pytest.fixture
def table(tmp_path):
    return build(tmp_path, {"models": ["機種A9", "機種A1"], "avoid_models": ["機種A5"]})


def check(text, table, facts_md=""):
    return at.check_table_numbers(text, table, facts_md)


def test_correct_numbers_pass_with_formatting_variants(table):
    for text in (
        "- 機種A9は3台で平均差枚 +400、勝率100%、G比1.00、10機種中1位。",
        "- 機種A9は平均＋４００、勝率１００％。",  # 全角
        "- 機種A1の平均差枚 −400、勝率0%。",  # 全角マイナス
    ):
        assert check(text, table) == ([], [])


def test_wrong_value_and_sign_fail(table):
    errors, _ = check("- 機種A9は平均差枚 +440。", table)
    assert errors and "機種A9" in errors[0] and "値が違う" in errors[0]
    errors, _ = check("- 機種A1は平均差枚 +400。", table)  # 実際は -400
    assert errors and "符号が逆" in errors[0]


def test_numbers_outside_table_are_warnings_not_errors(table):
    errors, warnings = check("- 末尾3の平均差枚 +777 が目立った。", table)
    assert errors == [] and warnings == ["平均差枚 +777"]


def test_hall_level_and_listed_models_are_not_attributed(table):
    # ホール平均の値を直前の機種の値と取り違えない
    assert check("- 機種A1は外れ（ホール平均 +31 を下回る）。", table)[0] == []
    # 並べた機種の合算値を最後の機種の値と取り違えない
    assert check("- 推した機種（機種A9・機種A1）: 6台、平均 +0", table)[0] == []


def test_baseline_and_other_day_lines_are_skipped(table):
    assert check("- 機種A9は過去の平均差枚 +999。", table) == ([], [])
    assert check("- 10/29の機種A9は平均差枚 +999。", table) == ([], [])


def test_verdict_contradiction_fails(table):
    errors, _ = check("- 機種A9は外れだった。", table)
    assert errors and "逆" in errors[0]
    assert check("- 機種A5は的中。", table)[0] == []  # 表は平ら。当たり/外れの断定とは言えない
    assert check("- 機種A9は当たり。", table)[0] == []
    assert check("- 機種A1の外れ値は…", table)[0] == []  # 「外れ値」は当たり外れではない


def test_no_table_means_no_check():
    assert at.check_table_numbers("- 平均差枚 +1", None, "") == ([], [])


# ---------------------------------------------------------------- 過去出力での誤検知

PAST_FALSE_POSITIVE_LIMIT = 2  # 2026-11-01 の測定: 112件中1件(データ遅れのarrowを「前日」で照合した測定側の誤り)


def test_past_outputs_false_positive_count_is_small():
    root = Path(__file__).resolve().parents[2]
    outputs = sorted((root / "output" / "morning_docs").glob("2026102*/*.answercheck.md"))
    if not outputs or not (root / "db").exists():
        pytest.skip("過去の朝出力が無い環境")
    import run_morning_docs as morning

    failed = 0
    seen = 0
    for path in outputs[:: max(1, len(outputs) // 12)]:  # 全件は遅いので等間隔に約12件
        key = path.name.split(".")[0]
        if key not in morning.HALLS:
            continue
        day = (datetime.strptime(path.parent.name, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        db = root / "db" / ("%s.db" % morning.HALLS[key][0])
        built = at.build_check_table(db, morning.PREDICTIONS, morning.ANNOUNCE_DIR, key, key, day)
        if built is None:
            continue
        text = "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("|"))
        seen += 1
        failed += bool(at.check_table_numbers(text, built, "")[0])
    assert seen == 0 or failed <= PAST_FALSE_POSITIVE_LIMIT
