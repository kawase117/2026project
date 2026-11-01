"""朝の下書きが、前日の文書や古い手本を真似ないこと。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_morning_docs as morning  # noqa: E402


def test_answercheck_prompt_has_own_structure_and_no_past_model():
    prompt = morning.answercheck_prompt("kamata7", "20261031", "20261101", Path("a.md"), "")
    assert "直近の `*-answercheck.md`" not in prompt
    for heading in ("予測との照合", "当日の実績", "学び", "今日（20261101）の予測への示唆"):
        assert heading in prompt
    assert "機械集計」の見出し・表" in prompt


def test_prediction_prompt_has_no_old_model_file():
    prompt = morning.prediction_prompt("kamata7", "20261101", "20261031", Path("a.md"), Path("b.md"))
    assert "2026-10-17-prediction.md" not in prompt and "体裁の手本" not in prompt


@pytest.mark.parametrize(
    "text",
    [
        "## 蒲田7\n\n### 機械集計（スクリプトがDBから計算）\n\n- 715台\n",
        "## 蒲田7\n\n#### 機械集計\n",
        "## 蒲田7\n\n| 機種 | 台数 | 平均差枚 | +2000以上の台 | 勝率 | 平均G |\n|---|---|---|---|---|---|\n",
        "## 蒲田7\n\n|機種|台数|平均差枚|\n",
    ],
)
def test_copied_facts_block_fails(text):
    assert morning.duplicate_facts_errors(text)


def test_clean_output_passes_duplicate_check():
    text = "## 蒲田7\n\n### 予測との照合\n\n機械集計の表は先頭に差し込まれる。\n\n| 機種 | 判定 |\n|---|---|\n"
    assert morning.duplicate_facts_errors(text) == []


def test_validate_answercheck_rejects_copied_facts():
    text = "## 蒲田7\n\n### 機械集計\n\n今日の予測への示唆\n"
    assert any("機械集計" in e for e in morning.validate_answercheck(text, "20261031"))


def test_missing_form_file_stops_prediction_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "PREDICTION_FORM_PATH", tmp_path / "none.md")
    with pytest.raises(morning.PredictionFormError):
        morning.prediction_form()
    with pytest.raises(morning.PredictionFormError):
        morning.prediction_prompt("kamata7", "20261101", "20261031", Path("a.md"), Path("b.md"))


@pytest.mark.parametrize("body", ["印が無い本文\n", "<!-- form:start -->\n\n<!-- form:end -->\n"])
def test_form_without_marker_or_empty_stops(tmp_path, monkeypatch, body):
    path = tmp_path / "SKILL.md"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(morning, "PREDICTION_FORM_PATH", path)
    with pytest.raises(morning.PredictionFormError):
        morning.prediction_form()
