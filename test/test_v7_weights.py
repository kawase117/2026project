from __future__ import annotations

from ml.experiments.walkforward_scoring.config import (
    COMPONENT_LIFT_V7,
    EXCLUDED_SEGMENTS_V7,
    SEGMENT_HIST_RATIO_V7,
    build_variant_configs,
    compute_v7_segment_weights,
)


def test_variant_configs_include_v7_lift_weights() -> None:
    variants = build_variant_configs()

    assert "v7_lift_weights" in variants
    assert variants["v7_lift_weights"].use_v7_weights is True
    assert variants["v6d_short_window_7"].use_v7_weights is False


def test_v7_weights_sum_to_struct_ratio() -> None:
    for segment in COMPONENT_LIFT_V7:
        hist_ratio = SEGMENT_HIST_RATIO_V7[segment]
        struct_ratio = 1.0 - hist_ratio
        weights = compute_v7_segment_weights(segment, struct_ratio)
        assert abs(sum(weights) - struct_ratio) < 1e-9


def test_v7_no_excluded_segments() -> None:
    assert len(EXCLUDED_SEGMENTS_V7) == 0

