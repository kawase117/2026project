"""category_high_share（「ジャグの20%⑤⑥」型）の推定と判定。"""

import numpy as np
import pandas as pd
import pytest

from backtest import announce
from backtest.announce import HIGH_SHARE_MIN_UNITS, estimate_high_share

# 合成スペック。設定1〜3は低め、4〜6は高め（RB・BBとも確率が上がる）。
SPEC = {
    "settings": {
        1: {"bb_probability": 1 / 280, "rb_probability": 1 / 420},
        2: {"bb_probability": 1 / 275, "rb_probability": 1 / 400},
        3: {"bb_probability": 1 / 270, "rb_probability": 1 / 370},
        4: {"bb_probability": 1 / 260, "rb_probability": 1 / 330},
        5: {"bb_probability": 1 / 245, "rb_probability": 1 / 290},
        6: {"bb_probability": 1 / 230, "rb_probability": 1 / 260},
    }
}


def _units(n, share, games=6000, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        setting = int(rng.choice([4, 5, 6])) if i < round(n * share) else int(rng.choice([1, 2, 3]))
        values = SPEC["settings"][setting]
        out.append(
            (
                SPEC,
                games,
                int(rng.binomial(games, values["bb_probability"])),
                int(rng.binomial(games, values["rb_probability"])),
            )
        )
    return out


def test_estimate_recovers_share_and_interval_covers_truth():
    # 95%区間は5%の確率で真値を外すので、1シードではなく複数シードで含有率を見る（実測98%）。
    ests = [estimate_high_share(_units(120, 0.3, seed=s)) for s in range(40)]
    assert all(e["n_units"] == 120 for e in ests)
    coverage = np.mean([e["ci_low"] <= 0.3 <= e["ci_high"] for e in ests])
    assert coverage >= 0.85
    assert abs(np.mean([e["share_hat"] for e in ests]) - 0.3) < 0.05  # 偏りがない


def test_estimate_is_low_when_no_high_settings():
    est = estimate_high_share(_units(120, 0.0, seed=1))
    assert est["ci_low"] < 0.05
    assert est["share_hat"] < 0.2


def test_too_few_units_returns_none():
    assert estimate_high_share(_units(HIGH_SHARE_MIN_UNITS - 1, 0.5)) is None


def _announce(claim):
    return {
        "announce_id": "t__20260101__x",
        "hall": "テスト",
        "target_date": "20260101",
        "source": {"account": "a", "url": "", "posted_at": "2025-12-31T20:00:00+09:00", "kind": "予告"},
        "raw_text": "x",
        "zentaikei": {"metric": "gratio_mean_diff", "threshold": 1800.0, "min_machines": 3},
        "claims": [claim],
    }


def test_validation_rejects_non_judgeable_category():
    with pytest.raises(ValueError, match="category_high_share.category"):
        announce.validate(_announce({"type": "category_high_share", "category": "bt_flag", "min_share": 0.2}))


def test_validation_rejects_bad_share_and_high_settings():
    with pytest.raises(ValueError, match="min_share"):
        announce.validate(_announce({"type": "category_high_share", "category": "jug_flag", "min_share": 0}))
    with pytest.raises(ValueError, match="high_settings"):
        announce.validate(
            _announce(
                {"type": "category_high_share", "category": "jug_flag", "min_share": 0.2, "high_settings": [0, 7]}
            )
        )


def test_validation_accepts_default_claim():
    announce.validate(_announce({"type": "category_high_share", "category": "jug_flag", "min_share": 0.2}))


def test_judge_verdict_levels(monkeypatch):
    # スペックを合成に差し替え、台データは3段階の割合で作る。
    monkeypatch.setattr("backtest.bonus_specs.load_specs", lambda hall=None: {"dummy": SPEC})
    monkeypatch.setattr("backtest.bonus_specs.find_spec", lambda name, specs=None: {**SPEC, "judgeable": True})

    def day(share):
        rows = []
        for i, (_, g, bb, rb) in enumerate(_units(150, share, seed=3)):
            rows.append(
                {
                    "machine_name": "ジャグA",
                    "machine_number": 1000 + i,
                    "games_normalized": g,
                    "bb_count": bb,
                    "rb_count": rb,
                    "jug_flag": 1,
                }
            )
        return pd.DataFrame(rows)

    claim = {"type": "category_high_share", "category": "jug_flag", "min_share": 0.2}
    inside = announce._judge_category_high_share(claim, "テスト", day(0.2))
    below = announce._judge_category_high_share(claim, "テスト", day(0.0))
    above = announce._judge_category_high_share({**claim, "min_share": 0.1}, "テスト", day(0.6))
    assert inside["verdict"] == "期待通り（矛盾なし）" and inside["hit"] is True
    assert below["verdict"] == "期待を下回る" and below["hit"] is False
    assert above["verdict"] == "期待を上回る" and above["hit"] is True


def test_judge_returns_none_when_category_missing():
    out = announce._judge_category_high_share(
        {"type": "category_high_share", "category": "jug_flag", "min_share": 0.2},
        "テスト",
        pd.DataFrame({"machine_name": ["x"]}),
    )
    assert out["hit"] is None
