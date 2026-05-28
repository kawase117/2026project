import pandas as pd

from ml.last_digit import tail_time_adaptive_ltr_poc_improved as improved
from ml.last_digit import tail_ltr_split_rule_nextday_gpu as nextday_gpu


def test_build_fixed_split_configs_adds_recent_standard_periods():
    dataset = pd.DataFrame({"date": ["2026-05-24", "2026-05-26", "2026-05-27"]})

    cfgs = improved.build_fixed_split_configs(dataset)

    assert cfgs["recent_90d_standard"] == {
        "train_start": improved.REGIME_1_START,
        "train_end": improved.REGIME_2_END,
        "valid_start": "2026-02-27",
        "valid_end": "2026-05-27",
    }
    assert cfgs["recent_60d_standard"] == {
        "train_start": improved.REGIME_1_START,
        "train_end": improved.REGIME_2_END,
        "valid_start": "2026-03-29",
        "valid_end": "2026-05-27",
    }


def test_build_fixed_split_configs_clamps_recent_periods_to_regime_3_start():
    dataset = pd.DataFrame({"date": ["2026-01-05", "2026-01-10"]})

    cfgs = improved.build_fixed_split_configs(dataset)

    assert cfgs["recent_90d_standard"]["valid_start"] == improved.REGIME_3_START
    assert cfgs["recent_60d_standard"]["valid_start"] == improved.REGIME_3_START


def test_nextday_parser_defaults_to_recent_90d_standard():
    parser = nextday_gpu.build_parser()

    args = parser.parse_args([])

    assert args.test_period_split_name == "recent_90d_standard"


def test_prepare_split_dataset_supports_past_target_date(monkeypatch):
    raw = pd.DataFrame(
        {
            "entity_key": ["2F_N|0", "2F_N|0", "2F_N|0"],
            "date": ["2026-05-24", "2026-05-25", "2026-05-26"],
            "group_key": ["2F_N", "2F_N", "2F_N"],
            "last_digit": ["0", "0", "0"],
            "total_diff_coins": [100.0, 200.0, 300.0],
            "total_diff_coins_focus": [100.0, 200.0, 300.0],
            "avg_diff_coins": [10.0, 20.0, 30.0],
            "win_rate": [0.1, 0.2, 0.3],
            "efficiency": [1.0, 2.0, 3.0],
            "efficiency_focus": [1.0, 2.0, 3.0],
            "is_rank_1": [0, 1, 0],
            "is_top_2": [0, 1, 0],
            "is_top_3": [1, 1, 0],
            "is_worst_1": [0, 0, 1],
            "is_worst_3": [0, 0, 1],
        }
    )

    monkeypatch.setattr(nextday_gpu, "resolve_db_path", lambda db_path, pattern: "dummy.db")
    monkeypatch.setattr(nextday_gpu, "build_base_rows", lambda db_path, a_weight, non_a_weight: raw.copy())
    monkeypatch.setattr(nextday_gpu, "aggregate_mode", lambda df, mode: df.copy())
    monkeypatch.setattr(nextday_gpu, "add_simple_features", lambda df, enable_digit_lag_bundle=False: df.copy())

    ext, source_latest, target_date = nextday_gpu._prepare_split_dataset(
        db_path="",
        db_glob="*7.db",
        a_weight=0.4,
        non_a_weight=1.3,
        enable_digit_lag_bundle=False,
        target_date="2026-05-26",
    )

    assert source_latest == pd.Timestamp("2026-05-25")
    assert target_date == pd.Timestamp("2026-05-26")
    assert ext["date"].max() == pd.Timestamp("2026-05-26")
    assert pd.Timestamp("2026-05-24") in ext["date"].tolist()
    assert pd.Timestamp("2026-05-25") in ext["date"].tolist()
    assert pd.Timestamp("2026-05-26") in ext["date"].tolist()
    assert ext[ext["date"] == pd.Timestamp("2026-05-26")]["total_diff_coins"].tolist() == [0.0]
