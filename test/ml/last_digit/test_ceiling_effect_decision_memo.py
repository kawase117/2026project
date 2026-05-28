import pandas as pd

from ml.last_digit.ceiling_effect.decision_report import generate_decision_memo


def _row(metric: str, delta: float, sig: int = 1, n_cur: int = 40, n_base: int = 40) -> dict:
    return {
        "condition": "weekday",
        "difficulty": "Monday",
        "metric": metric,
        "delta_mean": delta,
        "ci_low": delta - 0.01,
        "ci_high": delta + 0.01,
        "p_value_adj_bh": 0.01 if sig else 0.3,
        "sig_bh_0_05": sig,
        "cohens_d": abs(delta) * 10,
        "cohens_d_label": "small",
        "n_current": n_cur,
        "n_baseline": n_base,
    }


def test_decision_memo_recommended_when_no_major_worsening_and_no_low_support():
    df = pd.DataFrame(
        [
            _row("hit_at_2", +0.03, sig=1),
            _row("rank2_rescue_on_miss1", +0.20, sig=1),
            _row("loss_value", -500.0, sig=1),
        ]
    )
    memo = generate_decision_memo(df, {"current": {"unique_pairs": 429, "n_days": 143}})
    assert "採用推奨" in memo
    assert "BH有意悪化: 0件" in memo


def test_decision_memo_reject_when_major_metric_worsens():
    df = pd.DataFrame(
        [
            _row("hit_at_2", -0.02, sig=1),
            _row("rank2_rescue_on_miss1", +0.10, sig=1),
            _row("loss_value", -300.0, sig=1),
        ]
    )
    memo = generate_decision_memo(df, {})
    assert "非採用" in memo
    assert "悪化条件の有無: あり" in memo

