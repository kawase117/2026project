from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "walkforward_scoring" / "results"
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"

EVENT_DDS = frozenset({1, 7, 11, 17, 21, 22, 27, 31})
ANNIVERSARY_MMDD = "0707"
ZOROME_DIGITS = frozenset({"0", "5", "6", "9"})
COMPONENT_LIFT_V7 = {
    "2F_L_N": {"c1": 1.13, "c2": 1.00, "c4": 1.21, "c5": 1.02},
    "3F_L_A": {"c1": 1.07, "c2": 1.00, "c4": 1.02, "c5": 1.00},
    "3F_L_N": {"c1": 1.02, "c2": 1.12, "c4": 1.04, "c5": 1.00},
    "3F_R_A": {"c1": 1.07, "c2": 0.98, "c4": 1.04, "c5": 1.07},
    "3F_R_N": {"c1": 1.00, "c2": 1.01, "c4": 1.01, "c5": 0.96},
}
C3_DEFAULT_EXCESS = 0.03
C6_DEFAULT_EXCESS = 0.02
SEGMENT_HIST_RATIO_V7 = {
    "2F_L_N": 0.20,
    "3F_L_A": 0.15,
    "3F_L_N": 0.20,
    "3F_R_A": 0.05,
    "3F_R_N": 0.25,
}
EXCLUDED_SEGMENTS_V7 = frozenset()

DD_BINS = {
    1: "DD01-05",
    2: "DD01-05",
    3: "DD01-05",
    4: "DD01-05",
    5: "DD01-05",
    6: "DD06-11",
    7: "DD06-11",
    8: "DD06-11",
    9: "DD06-11",
    10: "DD06-11",
    11: "DD06-11",
    12: "DD12-17",
    13: "DD12-17",
    14: "DD12-17",
    15: "DD12-17",
    16: "DD12-17",
    17: "DD12-17",
    18: "DD18-23",
    19: "DD18-23",
    20: "DD18-23",
    21: "DD18-23",
    22: "DD18-23",
    23: "DD18-23",
    24: "DD24-28",
    25: "DD24-28",
    26: "DD24-28",
    27: "DD24-28",
    28: "DD24-28",
    29: "DD29-31",
    30: "DD29-31",
    31: "DD29-31",
}

SECTION_RANGES_2F = [
    (2001, 2010),
    (2011, 2022),
    (2023, 2031),
    (2032, 2040),
    (2041, 2052),
    (2053, 2064),
    (2065, 2076),
    (2077, 2088),
    (2089, 2101),
    (2102, 2114),
    (2115, 2128),
    (2129, 2142),
    (2143, 2154),
    (2155, 2164),
    (2165, 2171),
    (2172, 2178),
    (2179, 2186),
    (2187, 2195),
    (2196, 2212),
    (2213, 2229),
    (2230, 2246),
    (2247, 2263),
    (2264, 2280),
    (2281, 2297),
    (2298, 2313),
    (2314, 2329),
    (2330, 2351),
]

SECTION_RANGES_3F = [
    (3001, 3016),
    (3017, 3030),
    (3031, 3042),
    (3043, 3057),
    (3058, 3072),
    (3073, 3087),
    (3088, 3102),
    (3103, 3116),
    (3117, 3130),
    (3131, 3143),
    (3144, 3155),
    (3156, 3167),
    (3168, 3180),
    (3181, 3190),
    (3191, 3208),
    (3209, 3217),
    (3218, 3233),
    (3234, 3249),
    (3250, 3264),
    (3265, 3280),
    (3281, 3294),
    (3295, 3309),
    (3310, 3324),
    (3325, 3340),
    (3341, 3362),
    (3400, 3401),
]

REVERSED_OLD = frozenset({"2330-2351", "3191-3208", "3341-3362"})
REVERSED_NEW = frozenset(
    {
        "2023-2031",
        "2041-2052",
        "2065-2076",
        "2089-2101",
        "2115-2128",
        "2143-2154",
        "2165-2171",
        "2179-2186",
        "2196-2212",
        "2230-2246",
        "2264-2280",
        "2298-2313",
        "2330-2351",
        "3017-3030",
        "3043-3057",
        "3073-3087",
        "3103-3116",
        "3131-3143",
        "3156-3167",
        "3181-3190",
        "3218-3233",
        "3250-3264",
        "3281-3294",
        "3310-3324",
        "3341-3362",
        "3400-3401",
    }
)

DEFAULT_COMPONENT_WEIGHTS = (0.40, 0.15, 0.20, 0.15, 0.05, 0.05)
WEIGHT_GRID = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
HIT_AN_THRESHOLDS = {
    "A": 104.0,
    "N": 106.0,
}
SEGMENT_WEIGHTS_V6B = {
    "2F_L_N": (0.30, 0.00, 0.15, 0.35, 0.00, 0.10),
    "2F_R_N": (0.15, 0.15, 0.15, 0.15, 0.15, 0.15),
    "3F_L_A": (0.30, 0.00, 0.15, 0.15, 0.00, 0.30),
    "3F_L_N": (0.10, 0.30, 0.15, 0.15, 0.00, 0.00),
    "3F_R_A": (0.25, 0.00, 0.15, 0.20, 0.15, 0.15),
    "3F_R_N": (0.15, 0.15, 0.15, 0.15, 0.00, 0.30),
}

SEGMENT_WEIGHTS_V11 = {
    "3F_R_A": (0.28, 0.39, 0.03, 0.00, 0.30, 0.00),
    "3F_R_N": (0.50, 0.00, 0.00, 0.50, 0.00, 0.00),
    "2F_L_N": (0.34, 0.47, 0.05, 0.00, 0.07, 0.07),
}

DOW_SEGMENT_KAKUBAN_BOOST_V10 = {
    (3, "3F_L_A", "K5-9"): 1.20,
    (1, "3F_L_A", "K5-9"): 1.17,
    (4, "3F_L_A", "K5-9"): 1.12,
    (6, "3F_L_A", "K5-9"): 0.85,
    (3, "3F_L_A", "K10-14"): 1.15,
    (4, "3F_L_A", "K10-14"): 1.15,
    (5, "3F_L_A", "K10-14"): 0.87,
    (5, "3F_R_A", "K10-14"): 0.75,
    (5, "3F_R_A", "K3-4"): 0.78,
    (6, "3F_R_A", "K5-9"): 0.85,
}


@dataclass(frozen=True)
class VariantConfig:
    variant_id: str
    dd_mode: str
    hist_metric: str
    use_new_kakuban: bool
    optimize_weights: bool = False
    component_weights: tuple[float, float, float, float, float, float] = DEFAULT_COMPONENT_WEIGHTS
    use_segment_weights: bool = False
    use_v7_weights: bool = False
    use_v8_dynamic: bool = False
    blend_alpha: float = 1.0
    use_percentile_norm: bool = False
    hist_window_a: int | None = None
    hist_window_n: int | None = None
    use_dow_kakuban_boost: bool = False
    dow_kakuban_boost_scale: float = 1.0
    use_saturday_adjacent: bool = False
    saturday_adjacent_alpha: float = 0.3
    use_v11_weights: bool = False


def compute_segment_weights_from_lifts(
    lifts: dict[str, float],
    struct_ratio: float,
) -> tuple[float, float, float, float, float, float]:
    excess = {f"c{i}": max(0.0, float(lifts.get(f"c{i}", 1.0)) - 1.0) for i in range(1, 7)}
    total = sum(excess.values())
    if total <= 0.0:
        weight = struct_ratio / 6.0
        return (weight, weight, weight, weight, weight, weight)
    return tuple(excess[f"c{i}"] / total * struct_ratio for i in range(1, 7))


def compute_v7_segment_weights(
    segment: str,
    struct_ratio: float,
) -> tuple[float, float, float, float, float, float]:
    lifts = COMPONENT_LIFT_V7.get(segment)
    if lifts is None:
        weight = struct_ratio / 6.0
        return (weight, weight, weight, weight, weight, weight)

    excess = {
        "c1": max(0.0, lifts["c1"] - 1.0),
        "c2": max(0.0, lifts["c2"] - 1.0),
        "c3": C3_DEFAULT_EXCESS,
        "c4": max(0.0, lifts["c4"] - 1.0),
        "c5": max(0.0, lifts["c5"] - 1.0),
        "c6": C6_DEFAULT_EXCESS,
    }
    return compute_segment_weights_from_lifts(excess, struct_ratio)


def build_variant_configs() -> "OrderedDict[str, VariantConfig]":
    return OrderedDict(
        [
            (
                "v1_baseline",
                VariantConfig(
                    variant_id="v1_baseline",
                    dd_mode="bin",
                    hist_metric="diff",
                    use_new_kakuban=False,
                ),
            ),
            (
                "v2_dd_individual",
                VariantConfig(
                    variant_id="v2_dd_individual",
                    dd_mode="individual",
                    hist_metric="diff",
                    use_new_kakuban=False,
                ),
            ),
            (
                "v3_hist_payout",
                VariantConfig(
                    variant_id="v3_hist_payout",
                    dd_mode="individual",
                    hist_metric="payout",
                    use_new_kakuban=False,
                ),
            ),
            (
                "v4_kakuban_fix",
                VariantConfig(
                    variant_id="v4_kakuban_fix",
                    dd_mode="individual",
                    hist_metric="payout",
                    use_new_kakuban=True,
                ),
            ),
            (
                "v5_optimized",
                VariantConfig(
                    variant_id="v5_optimized",
                    dd_mode="individual",
                    hist_metric="payout",
                    use_new_kakuban=True,
                    optimize_weights=True,
                ),
            ),
            (
                "v6a_hit_an",
                VariantConfig(
                    variant_id="v6a_hit_an",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                ),
            ),
            (
                "v6b_seg_weights",
                VariantConfig(
                    variant_id="v6b_seg_weights",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_segment_weights=True,
                ),
            ),
            (
                "v6c_short_window_30",
                VariantConfig(
                    variant_id="v6c_short_window_30",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_segment_weights=True,
                    hist_window_a=30,
                ),
            ),
            (
                "v6d_short_window_7",
                VariantConfig(
                    variant_id="v6d_short_window_7",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_segment_weights=True,
                    hist_window_a=7,
                ),
            ),
            (
                "v7_lift_weights",
                VariantConfig(
                    variant_id="v7_lift_weights",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_v7_weights=True,
                ),
            ),
            (
                "v8_dynamic",
                VariantConfig(
                    variant_id="v8_dynamic",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_v8_dynamic=True,
                ),
            ),
            (
                "v9a_blend_07",
                VariantConfig(
                    variant_id="v9a_blend_07",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_v8_dynamic=True,
                    blend_alpha=0.7,
                ),
            ),
            (
                "v9b_blend_05",
                VariantConfig(
                    variant_id="v9b_blend_05",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_v8_dynamic=True,
                    blend_alpha=0.5,
                ),
            ),
            (
                "v9c_percentile",
                VariantConfig(
                    variant_id="v9c_percentile",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_v8_dynamic=True,
                    blend_alpha=0.0,
                    use_percentile_norm=True,
                ),
            ),
            (
                "v10a_dow_boost",
                VariantConfig(
                    variant_id="v10a_dow_boost",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_dow_kakuban_boost=True,
                ),
            ),
            (
                "v10b_sat_adj",
                VariantConfig(
                    variant_id="v10b_sat_adj",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_saturday_adjacent=True,
                    saturday_adjacent_alpha=0.3,
                ),
            ),
            (
                "v10c_full",
                VariantConfig(
                    variant_id="v10c_full",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_dow_kakuban_boost=True,
                    use_saturday_adjacent=True,
                    saturday_adjacent_alpha=0.3,
                ),
            ),
            (
                "v10d_boost_quarter",
                VariantConfig(
                    variant_id="v10d_boost_quarter",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_dow_kakuban_boost=True,
                    dow_kakuban_boost_scale=0.25,
                ),
            ),
            (
                "v10e_boost_half",
                VariantConfig(
                    variant_id="v10e_boost_half",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_dow_kakuban_boost=True,
                    dow_kakuban_boost_scale=0.50,
                ),
            ),
            (
                "v11_seg_weights",
                VariantConfig(
                    variant_id="v11_seg_weights",
                    dd_mode="individual",
                    hist_metric="hit_an",
                    use_new_kakuban=True,
                    use_v11_weights=True,
                ),
            ),
        ]
    )
