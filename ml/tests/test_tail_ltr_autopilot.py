import json
from pathlib import Path

import pandas as pd

from ml.experiments import tail_ltr_autopilot as autopilot


def test_build_trial_specs_applies_filters() -> None:
    split_windows = {
        "regime_fixed_split": {
            "split": {
                "train_start": "2025-07-07",
                "train_end": "2025-10-31",
                "valid_start": "2025-11-01",
                "valid_end": "2025-12-31",
            },
            "windows": {
                "recent_60d": {"train_start": "2025-09-02", "train_end": "2025-10-31"},
                "regime1_full": {"train_start": "2025-07-07", "train_end": "2025-10-31"},
            },
        },
        "regime_3_fixed_split": {
            "split": {
                "train_start": "2025-07-07",
                "train_end": "2025-12-31",
                "valid_start": "2026-01-01",
                "valid_end": "2026-05-12",
            },
            "windows": {
                "regime2_only": {"train_start": "2025-11-01", "train_end": "2025-12-31"},
            },
        },
    }
    trials = autopilot.build_trial_specs(
        split_windows=split_windows,
        targets=["is_top_2", "is_top_3"],
        lambdas_rank1=[1.0],
        lambdas_topk=[1.0, 2.0],
        seeds=[42],
        split_filter={"regime_3_fixed_split"},
        window_filter={"regime2_only"},
    )

    assert len(trials) == 4
    assert {t.split_name for t in trials} == {"regime_3_fixed_split"}
    assert {t.window_name for t in trials} == {"regime2_only"}
    assert {t.decay_lambda for t in trials} == {1.0, 2.0}


def test_load_done_keys_reads_trial_key_only() -> None:
    path = Path("tmp_test_tail_ltr_autopilot_records.jsonl")
    if path.exists():
        path.unlink()
    lines = [
        {"trial_key": "a|b|c", "value": 1},
        {"value": 2},
        "not_json",
    ]
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(lines[0], ensure_ascii=False) + "\n")
        f.write(json.dumps(lines[1], ensure_ascii=False) + "\n")
        f.write(str(lines[2]) + "\n")

    done = autopilot.load_done_keys(path)

    assert done == {"a|b|c"}
    path.unlink(missing_ok=True)


def test_build_split_windows_includes_train_windows(monkeypatch) -> None:
    dataset = pd.DataFrame({"date": pd.to_datetime(["2025-07-07", "2026-05-12"])})

    monkeypatch.setattr(
        autopilot.improved,
        "build_fixed_split_configs",
        lambda _dataset: {
            "regime_fixed_split": {
                "train_start": "2025-07-07",
                "train_end": "2025-10-31",
                "valid_start": "2025-11-01",
                "valid_end": "2025-12-31",
            }
        },
    )
    monkeypatch.setattr(
        autopilot.improved,
        "build_window_sweep_configs",
        lambda *, valid_start: {"recent_60d": {"train_start": "2025-09-02", "train_end": "2025-10-31"}},
    )

    result = autopilot.build_split_windows(dataset)

    assert "regime_fixed_split" in result
    assert result["regime_fixed_split"]["split"]["valid_start"] == "2025-11-01"
    assert "recent_60d" in result["regime_fixed_split"]["windows"]
