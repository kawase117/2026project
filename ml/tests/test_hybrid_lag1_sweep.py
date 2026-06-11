from pathlib import Path


def test_build_variant_specs_includes_baseline_and_lag1() -> None:
    from ml.last_digit import hybrid_lag1_sweep as mod

    specs = mod._build_variant_specs(
        base_output_root=Path("db/experiments/test"),
        hybrid_logreg_c=0.1,
        common_args=["--selection-start", "2025-07-07"],
    )
    assert [s["name"] for s in specs] == ["baseline", "lag1_games"]
    assert "--hybrid-use-lag1-games" not in specs[0]["args"]
    assert "--hybrid-use-lag1-games" in specs[1]["args"]
