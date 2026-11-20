"""朝の予測断片に対する純粋な書式検証。"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_morning_docs as morning  # noqa: E402

DAY = "20261120"


def check(body, *, hall="rakuen", baseline=(), candidates=frozenset(), announced=frozenset(), has_announcement=False):
    return morning.validate_prediction_fragment(
        "## ホール\n" + body, hall, DAY, set(candidates), tuple(baseline), set(announced), has_announcement
    )


def test_judgement_exactly_one_even_without_baseline_or_announcement():
    assert any("ちょうど1行" in e for e in check("試験枠: 自動候補。\n"))
    assert any("現在2行" in e for e in check("判断: 機種は推さない。\n判断: 追加。\n"))
    assert any("ちょうど1行" in e for e in check("- 判断: 機種は推さない。\n"))
    assert any("ちょうど1行" in e for e in check("判断： 機種は推さない。\n"))
    assert check("判断: 機種は推さない。\n") == []


def test_trial_and_body_numbers_require_hall_candidate():
    assert any("2046" in e for e in check("判断: 機種は推さない。\n試験枠: 2046番。\n"))
    assert any("2046" in e for e in check("判断: 機種は推さない。\n補足: 2046番を試す。\n"))
    assert check("判断: 機種は推さない。\n試験枠: 2046番。\n", candidates={"2046"}) == []
    assert check("判断: 機種は推さない。\n試験枠: 2046番。\n", announced={"2046"}, has_announcement=True) == []
    assert any(
        "2050" in e
        for e in check(
            "判断: 機種は推さない。\n試験枠: 2050番。\n", candidates={"2046"}, announced={"2046"}, has_announcement=True
        )
    )
    assert check("判断: 機種は推さない。\n試験枠: 2046番を外す(差枚 −212)。\n", candidates={"2046"}) == []


def test_avoid_past_result_rejected_and_structural_reason_accepted():
    assert any("過去の損益" in e for e in check("判断: 機種は推さない。\n避ける: A(前日は弱かった)。\n"))
    assert any("過去の損益" in e for e in check("判断: 機種は推さない。\n避ける: A(大外れ)。\n"))
    assert check("判断: 機種は推さない。\n避ける: A(機械割が低い)。\n") == []
    assert any("構造的理由" in e for e in check("判断: 機種は推さない。\n避ける: A(なんとなく)。\n"))


def test_baseline_first_and_judgement_starts_with_baseline_name():
    base = ("機種A", "機種B")
    assert any(
        "最初の行" in e for e in check("試験枠: 自動候補。\n基準: 機種A・機種B\n判断: 機種A・機種B。\n", baseline=base)
    )
    assert any("書き始める" in e for e in check("基準: 機種A・機種B\n判断: 基準の2機種。\n", baseline=base))
    assert check("基準: 機種A・機種B\n判断: 機種A・機種B(基準)。\n", baseline=base) == []
    assert check("基準: 機種A・機種B\n判断: 機種Aに機種Cを足す(公約)。\n", baseline=base) == []


def test_kamata7_without_announcement_does_not_name_baseline_models():
    base = ("戦国乙女4", "新鬼武者3")
    assert any(
        "予告のない蒲田7" in e
        for e in check("基準: 戦国乙女4・新鬼武者3\n判断: 戦国乙女4を推す。\n", hall="kamata7", baseline=base)
    )
    assert check("基準: 戦国乙女4・新鬼武者3\n判断: 機種は推さない。\n", hall="kamata7", baseline=base) == []
    assert (
        check(
            "基準: 戦国乙女4・新鬼武者3\n判断: 戦国乙女4を推す(予告)。\n",
            hall="kamata7",
            baseline=base,
            has_announcement=True,
        )
        == []
    )
    assert any("予告のない蒲田7" in e for e in check("判断: 戦国乙女4を推す。\n", hall="kamata7"))
    assert check("判断: 機種は推さない。\n", hall="kamata7") == []


def test_voided_announcement_is_not_active(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path)
    path = tmp_path / f"kamata7__{DAY}__acct.json"
    path.write_text(json.dumps({"raw_text": "狙い目は2046番", "amendments": [{"void": True}]}), encoding="utf-8")
    assert not morning.has_active_announcement("kamata7", DAY)
    assert morning.announce_numbers("kamata7", DAY) == set()


def test_candidate_numbers_are_scoped_to_hall_and_machine_rows(tmp_path):
    (tmp_path / "rb_candidates.md").write_text(
        "### 楽園蒲田店（DB最終日 20261119）\n"
        "| 候補 | A | 3000 | +0.1 |\n"
        "- A: 1174(+0.08)\n"
        "| A | 1104 | +0.10 | -0.20 |\n"
        "### レイトギャップ平和島（DB最終日 20261119）\n"
        "- B: 2046(+0.08)\n",
        encoding="utf-8",
    )
    (tmp_path / "rakuen.juggler.md").write_text("```\n1211 マイジャグラーV 1 3000\n```\n", encoding="utf-8")
    assert morning.candidate_numbers(tmp_path, "rakuen") == {"1174", "1104", "1211"}
