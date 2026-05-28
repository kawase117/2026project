import pandas as pd

from ml.last_digit.ceiling_effect.runner import (
    _build_run_diagnostics,
    _build_significance_summary_markdown,
)
from ml.last_digit.ceiling_effect.stats import StatsConfig


def _loss_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2026-01-01", "expert": "2F_N"},
            {"date": "2026-01-01", "expert": "3F_A"},
            {"date": "2026-01-02", "expert": "2F_N"},
        ]
    )


def test_build_run_diagnostics_includes_overlap_and_groups():
    cur = _loss_df()
    base = pd.DataFrame(
        [
            {"date": "2026-01-01", "expert": "2F_N"},
            {"date": "2026-01-03", "expert": "3F_A"},
        ]
    )
    metrics = pd.DataFrame(
        [
            {"condition": "weekday", "difficulty": "Monday"},
            {"condition": "weekday", "difficulty": "Tuesday"},
            {"condition": "anomaly_direction", "difficulty": "normal"},
        ]
    )
    sig = pd.DataFrame([{"sig_bh_0_05": 1}, {"sig_bh_0_05": 0}])
    out = _build_run_diagnostics(
        current_loss_df=cur,
        baseline_loss_df=base,
        condition_metrics=metrics,
        sig_df=sig,
        stats_config=StatsConfig(n_boot=100),
    )
    assert out["current"]["rows"] == 3
    assert out["current"]["unique_pairs"] == 3
    assert out["baseline"]["overlap_pairs"] == 1
    assert out["condition_group_count_by_condition"]["weekday"] == 2
    assert out["total_condition_groups"] == 3
    assert out["bootstrap_unit"] == "date_expert_pair"
    assert out["significance_rows"] == 2
    assert out["significance_sig_bh_0_05"] == 1


def test_build_significance_summary_markdown_sections():
    sig = pd.DataFrame(
        [
            {
                "condition": "weekday",
                "difficulty": "Monday",
                "metric": "hit_at_2",
                "delta_mean": 0.11,
                "p_value_adj_bh": 0.01,
                "sig_bh_0_05": 1,
                "cohens_d": 0.62,
                "cohens_d_label": "medium",
                "n_current": 50,
                "n_baseline": 50,
            },
            {
                "condition": "weekday",
                "difficulty": "Sunday",
                "metric": "loss_value",
                "delta_mean": -100.0,
                "p_value_adj_bh": 0.22,
                "sig_bh_0_05": 0,
                "cohens_d": 0.55,
                "cohens_d_label": "medium",
                "n_current": 8,
                "n_baseline": 9,
            },
        ]
    )
    md = _build_significance_summary_markdown(sig)
    assert "Top Significant Rows" in md
    assert "Non-significant But Large Effect" in md
    assert "Low-support Warnings" in md
    assert "weekday / Monday / hit_at_2" in md

