from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .config import (
    ANNIVERSARY_MMDD,
    DD_BINS,
    DEFAULT_COMPONENT_WEIGHTS,
    DOW_SEGMENT_KAKUBAN_BOOST_V10,
    EVENT_DDS,
    EXCLUDED_SEGMENTS_V7,
    HIT_AN_THRESHOLDS,
    PROJECT_ROOT,
    REVERSED_NEW,
    REVERSED_OLD,
    SEGMENT_HIST_RATIO_V7,
    SECTION_RANGES_2F,
    SECTION_RANGES_3F,
    SEGMENT_WEIGHTS_V6B,
    ZOROME_DIGITS,
    VariantConfig,
    WEIGHT_GRID,
    compute_segment_weights_from_lifts,
    compute_v7_segment_weights,
)


def classify_seg(machine_name: object) -> str:
    keywords = (
        "ジャグラー",
        "ハナハナ",
        "ファンキー",
        "アイム",
        "ゴーゴー",
        "キングハナ",
        "マイジャグラー",
    )
    text = "" if machine_name is None else str(machine_name)
    return "A" if any(keyword in text for keyword in keywords) else "N"


def _kakuban_group(kakuban: object) -> str:
    if pd.isna(kakuban):
        return ""
    value = int(kakuban)
    if value == 1:
        return "K1"
    if value == 2:
        return "K2"
    if value <= 4:
        return "K3-4"
    if value <= 9:
        return "K5-9"
    if value <= 14:
        return "K10-14"
    return "K15+"


def _segment_family(machine_name: object) -> str:
    return classify_seg(machine_name)


def _section_size_group(section_size: int | float | None) -> str:
    if section_size is None or pd.isna(section_size):
        return "unknown"
    value = int(section_size)
    if value <= 11:
        return "small"
    if value <= 14:
        return "medium"
    return "large"


def _calc_pay_rate(games_sum: pd.Series | pd.Index | np.ndarray, diff_sum: pd.Series | pd.Index | np.ndarray) -> pd.Series:
    denom = pd.to_numeric(games_sum, errors="coerce") * 3
    denom = denom.replace(0, np.nan)
    return ((denom + pd.to_numeric(diff_sum, errors="coerce")) / denom) * 100


def _resolve_default_db_path() -> Path:
    candidates = [path for path in (PROJECT_ROOT / "db").glob("*闥ｲ逕ｰ7*.db") if path.is_file() and path.stat().st_size > 0]
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]
    return PROJECT_ROOT / "db" / "繝槭Ν繝上Φ繝｡繧ｬ繧ｷ繝・ぅ2000-闥ｲ逕ｰ7.db"


@lru_cache(maxsize=1)
def load_coords_bundle(
    coords_2f: str | None = None,
    coords_3f: str | None = None,
) -> pd.DataFrame:
    path_2f = Path(coords_2f) if coords_2f else PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
    path_3f = Path(coords_3f) if coords_3f else PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
    frames: list[pd.DataFrame] = []
    for path in (path_2f, path_3f):
        frame = pd.read_csv(path)
        frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce").astype(int)
        frame["floor"] = frame["floor"].astype(str)
        frame["section"] = frame["section"].astype(str)
        frame["section_min"] = pd.to_numeric(frame["section_min"], errors="coerce").astype(int)
        frame["section_max"] = pd.to_numeric(frame["section_max"], errors="coerce").astype(int)
        frame["rank_from_min"] = pd.to_numeric(frame["rank_from_min"], errors="coerce").astype(int)
        frame["rank_from_max"] = pd.to_numeric(frame["rank_from_max"], errors="coerce").astype(int)
        frame["X"] = pd.to_numeric(frame["X"], errors="coerce")
        frame["section_size"] = frame.groupby("section", dropna=False)["machine_number"].transform("nunique").astype(int)
        frame["section_size_group"] = frame["section_size"].map(_section_size_group)
        frame["lr"] = _infer_lr(frame)
        frame["kakuban_old"] = frame.apply(lambda row: _calc_kakuban(row, use_new=False), axis=1)
        frame["kakuban_new"] = frame.apply(lambda row: _calc_kakuban(row, use_new=True), axis=1)
        frames.append(frame)
    coords = pd.concat(frames, ignore_index=True)
    return coords.drop_duplicates(subset=["machine_number"]).reset_index(drop=True)


def _infer_lr(coords: pd.DataFrame) -> pd.Series:
    out = pd.Series("Unknown", index=coords.index, dtype="string")
    if coords.empty:
        return out
    if "section" not in coords.columns or "X" not in coords.columns:
        return out
    x = pd.to_numeric(coords["X"], errors="coerce")
    section_nunique = x.groupby(coords["section"]).transform("nunique")
    section_median_x = x.groupby(coords["section"]).transform("median")
    floor_median_x = x.median()
    valid = x.notna() & section_median_x.notna()
    vertical = valid & (section_nunique == 1)
    normal = valid & ~vertical
    out.loc[normal & (x <= section_median_x)] = "L"
    out.loc[normal & (x > section_median_x)] = "R"
    out.loc[vertical & (x <= floor_median_x)] = "L"
    out.loc[vertical & (x > floor_median_x)] = "R"
    return out


def _calc_kakuban(row: pd.Series, *, use_new: bool) -> int:
    section_key = str(row["section"])
    reversed_set = REVERSED_NEW if use_new else REVERSED_OLD
    rank_from_min = int(row["rank_from_min"])
    rank_from_max = int(row["rank_from_max"])
    if section_key in reversed_set:
        return rank_from_max
    return rank_from_min


@dataclass(frozen=True)
class ScoreContext:
    coords: pd.DataFrame


def build_score_context(coords_2f: str | None = None, coords_3f: str | None = None) -> ScoreContext:
    return ScoreContext(coords=load_coords_bundle(coords_2f, coords_3f))


def _prepare_rows(frame: pd.DataFrame, context: ScoreContext) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = out["date"].astype(str)
    out["date_dt"] = pd.to_datetime(out["date"], errors="coerce")
    out["dd"] = out["date_dt"].dt.day.astype("Int64")
    out["dow"] = out["date_dt"].dt.dayofweek.astype("Int64")
    out["mmdd"] = out["date"].str[4:8]
    out["is_event"] = out["dd"].isin(EVENT_DDS)
    out["is_month_end"] = out["date_dt"].dt.is_month_end.fillna(False)
    out["is_0707"] = out["mmdd"].eq(ANNIVERSARY_MMDD)

    coords = context.coords[
        [
            "machine_number",
            "floor",
            "section",
            "section_min",
            "section_max",
            "rank_from_min",
            "rank_from_max",
            "section_size",
            "section_size_group",
            "lr",
            "kakuban_old",
            "kakuban_new",
        ]
    ].copy()
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce").astype("Int64")
    out = out.merge(coords, on="machine_number", how="left", validate="m:1")
    out["games_normalized"] = pd.to_numeric(out["games_normalized"], errors="coerce")
    out["diff_coins_normalized"] = pd.to_numeric(out["diff_coins_normalized"], errors="coerce")
    out["last_digit"] = out["last_digit"].astype(str)
    out["seg"] = out["machine_name"].map(classify_seg)
    out["segment"] = out["floor"].astype(str) + "_" + out["lr"].astype(str) + "_" + out["seg"].astype(str)
    out["hist_payout_row"] = ((out["games_normalized"] * 3 + out["diff_coins_normalized"]) / (out["games_normalized"] * 3)) * 100
    return out.dropna(subset=["date_dt", "machine_number", "floor", "section"]).reset_index(drop=True)


def _dd_key_for_row(dd: int, variant: VariantConfig) -> str | int:
    if variant.dd_mode == "bin":
        return DD_BINS[int(dd)]
    return int(dd)


def _lookup_mean(frame: pd.DataFrame, key_cols: list[str], value_col: str = "diff_coins_normalized") -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=key_cols + ["value", "n"])
    grouped = frame.groupby(key_cols, dropna=False)[value_col].agg(value="mean", n="size").reset_index()
    return grouped


def _hier_lookup(
    target: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    exact_keys: list[str],
    fallback_keys: list[list[str]],
) -> pd.Series:
    out = pd.Series(np.nan, index=target.index, dtype="float64")
    current = _lookup_mean(frame, exact_keys)
    out = out.combine_first(target.merge(current[exact_keys + ["value"]], on=exact_keys, how="left")["value"])
    for key_cols in fallback_keys:
        current = _lookup_mean(frame, key_cols)
        out = out.combine_first(target.merge(current[key_cols + ["value"]], on=key_cols, how="left")["value"])
    return out.fillna(0.0)


def _build_component_columns(
    train: pd.DataFrame,
    actual: pd.DataFrame,
    variant: VariantConfig,
    test_date: pd.Timestamp,
    *,
    full_train: pd.DataFrame | None = None,
) -> pd.DataFrame:
    train = train.copy()
    train["kakuban"] = train["kakuban_new" if variant.use_new_kakuban else "kakuban_old"].astype("Int64")
    train["segment"] = train["segment"].astype(str)
    train["section_size_group"] = train["section_size_group"].astype(str)

    work = actual.copy()
    work["kakuban"] = work["kakuban_new" if variant.use_new_kakuban else "kakuban_old"].astype("Int64")
    work["dd_key"] = _dd_key_for_row(int(test_date.day), variant)
    work["dow_key"] = int(test_date.dayofweek)

    train_dd = train[train["date_dt"].dt.day.eq(test_date.day)].copy()
    train_dow = train[train["date_dt"].dt.dayofweek.eq(test_date.dayofweek)].copy()

    work["c1"] = _hier_lookup(
        work,
        train,
        exact_keys=["segment", "section_size_group", "kakuban"],
        fallback_keys=[["section_size_group", "kakuban"], ["kakuban"]],
    )
    if variant.use_dow_kakuban_boost:
        kakuban_group = work["kakuban"].map(_kakuban_group)
        boost = pd.Series(1.0, index=work.index, dtype="float64")
        for (dow_key, segment, group), multiplier in DOW_SEGMENT_KAKUBAN_BOOST_V10.items():
            mask = (
                work["dow_key"].eq(int(dow_key))
                & work["segment"].eq(str(segment))
                & kakuban_group.eq(str(group))
            )
            scaled = 1.0 + variant.dow_kakuban_boost_scale * (float(multiplier) - 1.0)
            boost.loc[mask] = scaled
        work["c1"] = work["c1"] * boost

    work["c2"] = work.apply(lambda row: _calc_c2(row), axis=1)

    if variant.dd_mode == "bin":
        target_bin = DD_BINS[int(test_date.day)]
        c3_source = train[train["date_dt"].dt.day.map(lambda value: DD_BINS.get(int(value), "")) == target_bin].copy()
    else:
        c3_source = train_dd.copy() if not train_dd.empty else train.copy()
    work["c3"] = _hier_lookup(
        work,
        c3_source,
        exact_keys=["segment", "kakuban"],
        fallback_keys=[["section_size_group", "kakuban"], ["kakuban"]],
    )

    c4_frame = train_dow if not train_dow.empty else train
    work["c4"] = _hier_lookup(
        work,
        c4_frame,
        exact_keys=["segment", "kakuban"],
        fallback_keys=[["section_size_group", "kakuban"], ["kakuban"]],
    )

    c5_gate_source = full_train if full_train is not None else train
    c5_significant_segments: set[str] = set()
    from scipy.stats import kruskal as _kruskal
    for segment, group in c5_gate_source.groupby("segment", dropna=False):
        digit_groups = group.groupby("last_digit")["diff_coins_normalized"].apply(list)
        if len(digit_groups) >= 2 and all(len(v) >= 3 for v in digit_groups.values):
            try:
                _, p = _kruskal(*digit_groups.values)
            except ValueError:
                p = 1.0
            if p < 0.05:
                c5_significant_segments.add(str(segment))
    c5_lookup_by_segment: dict[str, dict[str, float]] = {}
    for segment, group in train.groupby("segment", dropna=False):
        if str(segment) in c5_significant_segments:
            c5_lookup_by_segment[str(segment)] = group.groupby("last_digit")["diff_coins_normalized"].mean().to_dict()
    work["c5"] = work.apply(
        lambda row: float(c5_lookup_by_segment.get(str(row["segment"]), {}).get(str(row["last_digit"]), 0.0)),
        axis=1,
    )

    if variant.use_v7_weights:
        if "is_zorome" in train.columns:
            train["is_zorome"] = pd.to_numeric(train["is_zorome"], errors="coerce").fillna(0).astype(int)
        else:
            train["is_zorome"] = 0
        if "is_zorome" in work.columns:
            work["is_zorome"] = pd.to_numeric(work["is_zorome"], errors="coerce").fillna(0).astype(int)
        else:
            work["is_zorome"] = 0
        c6_source = train[train["date_dt"].dt.day.eq(test_date.day)].copy()
        if c6_source.empty:
            c6_source = train.copy()

        c6_lookup: dict[str, float] = {}
        for segment, group in c6_source.groupby("segment", dropna=False):
            zorome_avg = pd.to_numeric(
                group.loc[group["is_zorome"].eq(1), "diff_coins_normalized"], errors="coerce"
            ).mean()
            non_zorome_avg = pd.to_numeric(
                group.loc[group["is_zorome"].eq(0), "diff_coins_normalized"], errors="coerce"
            ).mean()
            c6_lookup[str(segment)] = _calc_c6_zorome(1, zorome_avg, non_zorome_avg)

        work["c6"] = work.apply(
            lambda row: _calc_c6_zorome(
                int(row.get("is_zorome", 0)),
                c6_lookup.get(str(row["segment"]), 0.0),
                0.0,
            ),
            axis=1,
        )
    else:
        work["c6"] = work["last_digit"].map(lambda value: _calc_c6(value))

    hist = _build_hist_features(train, work, variant)
    for column in ("hist_diff", "hist_payout", "hist_winrate", "hist_hit_an", "a_seg_hist_coverage", "a_seg_fallback_count"):
        work[column] = hist[column]

    return work


def _calc_c2(row: pd.Series) -> float:
    optimal = {"small": 5, "medium": 6, "large": 11}.get(str(row["section_size_group"]), 6)
    kakuban = int(row["kakuban"])
    return float(max(0, 200 - abs(kakuban - optimal) * 50))


def _calc_c5(row: pd.Series) -> float:
    if str(row["segment"]) != "3F_L_N":
        return 0.0
    lookup = {"0", "5", "9", "6"}
    return 50.0 if str(row["last_digit"]) in lookup else 0.0


def _calc_c6(last_digit: object) -> float:
    return 50.0 if str(last_digit) in ZOROME_DIGITS else 0.0


def _calc_c6_zorome(is_zorome_flag: int, zorome_avg: float | None, non_zorome_avg: float | None) -> float:
    if int(is_zorome_flag) != 1:
        return 0.0
    if pd.isna(zorome_avg) or pd.isna(non_zorome_avg):
        return 0.0
    return float(zorome_avg - non_zorome_avg)


def _build_hist_features(train: pd.DataFrame, actual: pd.DataFrame, variant: VariantConfig) -> pd.DataFrame:
    hist_cols = ["hist_diff", "hist_payout", "hist_winrate", "hist_hit_an", "a_seg_hist_coverage", "a_seg_fallback_count"]
    if actual.empty:
        return pd.DataFrame({col: np.zeros(0, dtype=float) for col in hist_cols}, index=actual.index)
    if train.empty:
        return pd.DataFrame({col: np.zeros(len(actual), dtype=float) for col in hist_cols}, index=actual.index)

    grouped = (
        train.groupby("machine_number", dropna=False)
        .agg(
            hist_diff=("diff_coins_normalized", "mean"),
            hist_payout=("hist_payout_row", "mean"),
            hist_winrate=("diff_coins_normalized", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean())),
        )
        .reset_index()
    )
    merged = actual.reset_index(drop=False).rename(columns={"index": "_actual_index"}).merge(grouped, on="machine_number", how="left")
    merged["hist_hit_an"] = 0.0
    merged["a_seg_hist_coverage"] = 0.0
    merged["a_seg_fallback_count"] = 0.0

    train_by_machine = {
        machine_number: group.sort_values("date_dt")
        for machine_number, group in train.groupby("machine_number", dropna=False)
    }

    actual_records = merged.to_dict("records")
    a_records = [row for row in actual_records if _segment_family(row.get("machine_name")) == "A"]
    a_total = len(a_records)
    a_with_hist = 0
    a_fallback = 0

    family_rows: list[dict[str, object]] = []
    for row in actual_records:
        family = _segment_family(row.get("machine_name"))
        machine_history = train_by_machine.get(row.get("machine_number"))
        threshold = HIT_AN_THRESHOLDS.get(family, 104.0)
        if machine_history is None or machine_history.empty:
            if family == "A":
                a_fallback += 1
            family_rows.append(
                {
                    "_actual_index": row.get("_actual_index"),
                    "hist_hit_an": 0.0,
                    "a_seg_hist_coverage": np.nan if family == "A" else 0.0,
                    "a_seg_fallback_count": np.nan if family == "A" else 0.0,
                }
            )
            continue

        if family == "A" and variant.hist_window_a is not None:
            cutoff = pd.Timestamp(row.get("date_dt")) - pd.Timedelta(days=int(variant.hist_window_a))
            window_history = machine_history[machine_history["date_dt"] >= cutoff]
        elif family == "N" and variant.hist_window_n is not None:
            cutoff = pd.Timestamp(row.get("date_dt")) - pd.Timedelta(days=int(variant.hist_window_n))
            window_history = machine_history[machine_history["date_dt"] >= cutoff]
        else:
            window_history = machine_history

        if window_history.empty:
            hist_hit_an = 0.0
            fallback = 1.0 if family == "A" and (variant.hist_window_a is not None or variant.hist_window_n is not None) else 0.0
            coverage = np.nan
            if family == "A":
                a_fallback += 1
        else:
            payout_rate = pd.to_numeric(window_history["hist_payout_row"], errors="coerce")
            hist_hit_an = float((payout_rate >= threshold).mean()) * 100.0
            fallback = 0.0
            coverage = np.nan
            if family == "A":
                a_with_hist += 1

        family_rows.append(
            {
                "_actual_index": row.get("_actual_index"),
                "hist_hit_an": hist_hit_an,
                "a_seg_hist_coverage": np.nan if family == "A" else 0.0,
                "a_seg_fallback_count": np.nan if family == "A" else 0.0,
            }
        )

    family_df = pd.DataFrame(family_rows).set_index("_actual_index")
    a_coverage = (a_with_hist / a_total * 100.0) if a_total > 0 else 0.0
    a_fallback = float(a_fallback)
    merged = merged.set_index("_actual_index")
    merged["hist_hit_an"] = family_df["hist_hit_an"]
    merged["a_seg_hist_coverage"] = family_df["a_seg_hist_coverage"].fillna(a_coverage)
    merged["a_seg_fallback_count"] = family_df["a_seg_fallback_count"].fillna(a_fallback)
    merged = merged.reset_index()
    for col in hist_cols:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
    return merged[hist_cols]


def _component_weights_for_variant(variant: VariantConfig, weight_override: tuple[float, float, float, float, float, float] | None) -> tuple[float, float, float, float, float, float]:
    if weight_override is not None:
        return weight_override
    return variant.component_weights


def _score_from_components(
    frame: pd.DataFrame,
    weights: tuple[float, float, float, float, float, float],
    *,
    use_segment_weights: bool = False,
) -> pd.Series:
    if use_segment_weights and "segment" in frame.columns:
        def _score_row(row: pd.Series) -> float:
            row_weights = SEGMENT_WEIGHTS_V6B.get(str(row["segment"]), weights)
            struct = (
                row["c1"] * row_weights[0]
                + row["c2"] * row_weights[1]
                + row["c3"] * row_weights[2]
                + row["c4"] * row_weights[3]
                + row["c5"] * row_weights[4]
                + row["c6"] * row_weights[5]
            )
            return float(struct * 0.90 + row["hist_metric"] * 0.10)

        return frame.apply(_score_row, axis=1)

    struct = (
        frame["c1"] * weights[0]
        + frame["c2"] * weights[1]
        + frame["c3"] * weights[2]
        + frame["c4"] * weights[3]
        + frame["c5"] * weights[4]
        + frame["c6"] * weights[5]
    )
    return struct * 0.90 + frame["hist_metric"] * 0.10


def _score_from_components_v7(frame: pd.DataFrame) -> pd.Series:
    def _score_row(row: pd.Series) -> float:
        segment = str(row["segment"])
        if segment in EXCLUDED_SEGMENTS_V7:
            return float("nan")
        hist_ratio = SEGMENT_HIST_RATIO_V7.get(segment, 0.10)
        struct_ratio = 1.0 - hist_ratio
        weights = compute_v7_segment_weights(segment, struct_ratio)
        struct = (
            row["c1"] * weights[0]
            + row["c2"] * weights[1]
            + row["c3"] * weights[2]
            + row["c4"] * weights[3]
            + row["c5"] * weights[4]
            + row["c6"] * weights[5]
        )
        return float(struct + row["hist_metric"] * hist_ratio)

    return frame.apply(_score_row, axis=1)


def _build_dynamic_lift_proxy_frame(
    train: pd.DataFrame,
    segment: str,
) -> pd.DataFrame:
    work = train.copy()
    if "segment" not in work.columns or "diff_coins_normalized" not in work.columns:
        return pd.DataFrame()
    if "date_dt" not in work.columns:
        if "date" in work.columns:
            work["date_dt"] = pd.to_datetime(work["date"], errors="coerce")
        else:
            work["date_dt"] = pd.NaT

    if "kakuban" not in work.columns:
        kakuban_source = "kakuban_new" if "kakuban_new" in work.columns else "kakuban_old" if "kakuban_old" in work.columns else None
        if kakuban_source is not None:
            work["kakuban"] = pd.to_numeric(work[kakuban_source], errors="coerce").astype("Int64")
        else:
            work["kakuban"] = pd.Series([pd.NA] * len(work), dtype="Int64")
    else:
        work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce").astype("Int64")

    if "section_size_group" not in work.columns:
        work["section_size_group"] = "unknown"
    if "last_digit" not in work.columns:
        work["last_digit"] = "0"
    else:
        work["last_digit"] = work["last_digit"].astype(str)
    if "is_zorome" in work.columns:
        work["is_zorome"] = pd.to_numeric(work["is_zorome"], errors="coerce").fillna(0).astype(int)
    else:
        work["is_zorome"] = 0

    seg_train = work[work["segment"] == segment].copy()
    if seg_train.empty:
        return seg_train

    seg_train["c1"] = _hier_lookup(
        seg_train,
        work,
        exact_keys=["segment", "section_size_group", "kakuban"],
        fallback_keys=[["section_size_group", "kakuban"], ["kakuban"]],
    )
    seg_train["c2"] = seg_train.apply(lambda row: _calc_c2(row), axis=1)

    seg_train["c3"] = 0.0
    if seg_train["date_dt"].notna().any():
        for dd_value in sorted(seg_train["date_dt"].dt.day.dropna().astype(int).unique()):
            mask = seg_train["date_dt"].dt.day.eq(dd_value)
            source = work[work["date_dt"].dt.day.eq(dd_value)].copy()
            if source.empty:
                source = work
            seg_train.loc[mask, "c3"] = _hier_lookup(
                seg_train.loc[mask],
                source,
                exact_keys=["segment", "kakuban"],
                fallback_keys=[["section_size_group", "kakuban"], ["kakuban"]],
            )

    seg_train["c4"] = 0.0
    if seg_train["date_dt"].notna().any():
        for dow_value in sorted(seg_train["date_dt"].dt.dayofweek.dropna().astype(int).unique()):
            mask = seg_train["date_dt"].dt.dayofweek.eq(dow_value)
            source = work[work["date_dt"].dt.dayofweek.eq(dow_value)].copy()
            if source.empty:
                source = work
            seg_train.loc[mask, "c4"] = _hier_lookup(
                seg_train.loc[mask],
                source,
                exact_keys=["segment", "kakuban"],
                fallback_keys=[["section_size_group", "kakuban"], ["kakuban"]],
            )

    from scipy.stats import kruskal as _kruskal

    c5_significant_segments: set[str] = set()
    for seg_key, group in work.groupby("segment", dropna=False):
        digit_groups = group.groupby("last_digit")["diff_coins_normalized"].apply(list)
        if len(digit_groups) >= 2 and all(len(values) >= 3 for values in digit_groups.values):
            try:
                _, p_value = _kruskal(*digit_groups.values)
            except ValueError:
                p_value = 1.0
            if p_value < 0.05:
                c5_significant_segments.add(str(seg_key))

    c5_lookup_by_segment: dict[str, dict[str, float]] = {}
    for seg_key, group in work.groupby("segment", dropna=False):
        if str(seg_key) in c5_significant_segments:
            c5_lookup_by_segment[str(seg_key)] = group.groupby("last_digit")["diff_coins_normalized"].mean().to_dict()
    seg_train["c5"] = seg_train.apply(
        lambda row: float(c5_lookup_by_segment.get(str(row["segment"]), {}).get(str(row["last_digit"]), 0.0)),
        axis=1,
    )

    seg_train["c6"] = seg_train["last_digit"].map(lambda value: _calc_c6(value))
    return seg_train


def _compute_dynamic_lifts(
    train: pd.DataFrame,
    segment: str,
    components: tuple[str, ...] = ("c1", "c2", "c3", "c4", "c5", "c6"),
    top_fraction: float = 0.20,
) -> dict[str, float]:
    seg_train = _build_dynamic_lift_proxy_frame(train, segment)
    if len(seg_train) < 50:
        return {component: 1.0 for component in components}

    overall_mean = pd.to_numeric(seg_train["diff_coins_normalized"], errors="coerce").mean()
    if pd.isna(overall_mean) or overall_mean <= 0:
        return {component: 1.0 for component in components}

    k = max(1, int(len(seg_train) * top_fraction))
    lifts: dict[str, float] = {}
    for component in components:
        if component not in seg_train.columns:
            lifts[component] = 1.0
            continue
        values = pd.to_numeric(seg_train[component], errors="coerce")
        valid = seg_train.assign(_component=values).dropna(subset=["_component", "diff_coins_normalized"])
        if valid.empty:
            lifts[component] = 1.0
            continue
        top_mean = valid.nlargest(k, "_component")["diff_coins_normalized"].mean()
        lift = float(top_mean / overall_mean) if overall_mean > 0 else 1.0
        lifts[component] = lift if pd.notna(lift) and lift > 0 else 1.0
    for key in lifts:
        lifts[key] = max(0.5, min(3.0, lifts[key]))
    return lifts


def _compute_dynamic_hist_ratio(
    train: pd.DataFrame,
    segment: str,
    *,
    min_samples: int = 100,
    default_ratio: float = 0.10,
) -> float:
    seg_train = train[train["segment"] == segment].copy()
    if len(seg_train) < min_samples or "hist_metric" not in seg_train.columns:
        return default_ratio

    valid = seg_train.dropna(subset=["hist_metric", "diff_coins_normalized"])
    if len(valid) < min_samples:
        return default_ratio

    from scipy.stats import spearmanr

    rho, _ = spearmanr(valid["hist_metric"], valid["diff_coins_normalized"])
    if pd.isna(rho):
        return default_ratio
    return float(max(0.05, min(0.25, 0.05 + float(rho))))


MIN_LIFT_EXCESS_FOR_DYNAMIC = 0.02

_v8_lift_cache: dict[tuple[str, str], dict[str, float]] = {}
_v8_hist_ratio_cache: dict[tuple[str, str], float] = {}


def clear_v8_lift_cache() -> None:
    _v8_lift_cache.clear()
    _v8_hist_ratio_cache.clear()


def _score_from_components_v8(
    frame: pd.DataFrame,
    train: pd.DataFrame,
    *,
    test_date: pd.Timestamp | None = None,
) -> pd.Series:
    month_key = test_date.strftime("%Y-%m") if test_date is not None else ""
    segments = [str(value) for value in frame["segment"].dropna().unique()]
    segment_lifts: dict[str, dict[str, float]] = {}
    segment_hist_ratios: dict[str, float] = {}
    for segment in segments:
        cache_key = (segment, month_key)
        if cache_key in _v8_lift_cache:
            segment_lifts[segment] = _v8_lift_cache[cache_key]
            segment_hist_ratios[segment] = _v8_hist_ratio_cache.get(cache_key, 0.10)
        else:
            lifts = _compute_dynamic_lifts(train, segment)
            hist_ratio = _compute_dynamic_hist_ratio(train, segment)
            _v8_lift_cache[cache_key] = lifts
            _v8_hist_ratio_cache[cache_key] = hist_ratio
            segment_lifts[segment] = lifts
            segment_hist_ratios[segment] = hist_ratio

    def _score_row(row: pd.Series) -> float:
        segment = str(row["segment"])
        lifts = segment_lifts.get(segment)
        if lifts is None:
            return float("nan")
        max_excess = max(v - 1.0 for v in lifts.values())
        if max_excess < MIN_LIFT_EXCESS_FOR_DYNAMIC:
            struct = (
                row["c1"] * DEFAULT_COMPONENT_WEIGHTS[0]
                + row["c2"] * DEFAULT_COMPONENT_WEIGHTS[1]
                + row["c3"] * DEFAULT_COMPONENT_WEIGHTS[2]
                + row["c4"] * DEFAULT_COMPONENT_WEIGHTS[3]
                + row["c5"] * DEFAULT_COMPONENT_WEIGHTS[4]
                + row["c6"] * DEFAULT_COMPONENT_WEIGHTS[5]
            )
            return float(struct * 0.90 + row["hist_metric"] * 0.10)
        hist_ratio = segment_hist_ratios.get(segment, 0.10)
        struct_ratio = 1.0 - hist_ratio
        weights = compute_segment_weights_from_lifts(lifts, struct_ratio)
        struct = (
            row["c1"] * weights[0]
            + row["c2"] * weights[1]
            + row["c3"] * weights[2]
            + row["c4"] * weights[3]
            + row["c5"] * weights[4]
            + row["c6"] * weights[5]
        )
        return float(struct + row["hist_metric"] * hist_ratio)

    return frame.apply(_score_row, axis=1)


def _segment_strength_weights(train: pd.DataFrame) -> pd.Series:
    seg_strength = train.groupby("segment", dropna=False)["diff_coins_normalized"].mean()
    seg_min = seg_strength.min()
    seg_max = seg_strength.max()
    if pd.isna(seg_min) or pd.isna(seg_max) or seg_max <= seg_min:
        return pd.Series(1.0, index=seg_strength.index)
    return 0.5 + 0.5 * (seg_strength - seg_min) / (seg_max - seg_min)


def _blend_v9_scores(frame: pd.DataFrame, train: pd.DataFrame, segment_score: pd.Series) -> pd.Series:
    work = frame.copy()
    work["_seg_score"] = segment_score
    work["seg_percentile"] = work.groupby("segment", dropna=False)["_seg_score"].rank(pct=True)
    seg_weight = _segment_strength_weights(train)
    return work["seg_percentile"] * work["segment"].map(seg_weight).fillna(0.75)


def _hist_metric_series(frame: pd.DataFrame, metric: str) -> pd.Series:
    if metric == "diff":
        return frame["hist_diff"]
    if metric == "payout":
        return frame["hist_payout"]
    if metric == "winrate":
        return frame["hist_winrate"]
    if metric == "hit_an":
        return frame["hist_hit_an"]
    raise ValueError(f"Unknown hist metric: {metric}")


def score_day(
    train: pd.DataFrame,
    actual: pd.DataFrame,
    variant: VariantConfig,
    *,
    test_date: str | pd.Timestamp | None = None,
    context: ScoreContext | None = None,
    weight_override: tuple[float, float, float, float, float, float] | None = None,
    full_train: pd.DataFrame | None = None,
) -> pd.DataFrame:
    context = context or build_score_context()
    train_p = _prepare_rows(train, context)
    actual_p = _prepare_rows(actual, context)
    full_train_p = _prepare_rows(full_train, context) if full_train is not None else None
    if test_date is None:
        if actual_p.empty:
            return actual_p
        test_date = actual_p["date_dt"].iloc[0]
    test_dt = pd.Timestamp(test_date).normalize()
    train_p = train_p[(train_p["date_dt"] < test_dt) & (~train_p["is_0707"])].copy()
    actual_p = actual_p[(actual_p["date_dt"] == test_dt) & (~actual_p["is_0707"])].copy()
    if full_train_p is not None:
        full_train_p = full_train_p[(full_train_p["date_dt"] < test_dt) & (~full_train_p["is_0707"])].copy()
    if actual_p.empty:
        return actual_p

    work = _build_component_columns(train_p, actual_p, variant, test_dt, full_train=full_train_p)
    work["hist_metric"] = _hist_metric_series(work, variant.hist_metric)
    if variant.use_v8_dynamic:
        segment_score = _score_from_components_v8(work, train_p, test_date=test_dt)
        if variant.use_percentile_norm:
            work["composite"] = _blend_v9_scores(work, train_p, segment_score)
        elif variant.blend_alpha < 1.0:
            global_score = _score_from_components(work, DEFAULT_COMPONENT_WEIGHTS, use_segment_weights=False)
            work["composite"] = variant.blend_alpha * global_score + (1 - variant.blend_alpha) * segment_score
        else:
            work["composite"] = segment_score
    elif variant.use_v7_weights:
        work["composite"] = _score_from_components_v7(work)
        work = work.dropna(subset=["composite"]).copy()
    else:
        weights = _component_weights_for_variant(variant, weight_override)
        work["composite"] = _score_from_components(work, weights, use_segment_weights=variant.use_segment_weights)
    if variant.use_saturday_adjacent and test_dt.dayofweek == 5:
        work = work.sort_values(["section", "machine_number"], na_position="last").copy()
        work["prev_composite"] = work.groupby("section", dropna=False)["composite"].shift(1)
        work["next_composite"] = work.groupby("section", dropna=False)["composite"].shift(-1)
        adj_mean = work[["prev_composite", "next_composite"]].mean(axis=1, skipna=True)
        adj_mean = adj_mean.fillna(work["composite"])
        alpha = float(variant.saturday_adjacent_alpha)
        work["composite"] = (1.0 - alpha) * work["composite"] + alpha * adj_mean
        work = work.drop(columns=["prev_composite", "next_composite"])
    work["dd_key"] = work["dd"].map(lambda value: _dd_key_for_row(int(value), variant))
    work["variant"] = variant.variant_id
    work["test_date"] = work["date_dt"].dt.strftime("%Y-%m-%d")
    work["dow_name"] = work["date_dt"].dt.day_name()
    return work.sort_values(["composite", "diff_coins_normalized", "machine_number"], ascending=[False, False, True]).reset_index(drop=True)


def candidate_weights() -> list[tuple[float, float, float, float, float, float]]:
    candidates: list[tuple[float, float, float, float, float, float]] = []
    target = 0.90
    for w1 in WEIGHT_GRID:
        for w2 in WEIGHT_GRID:
            for w3 in WEIGHT_GRID:
                for w4 in WEIGHT_GRID:
                    if abs((w1 + w2 + w3 + w4) - target) < 1e-9:
                        candidates.append((w1, w2, w3, w4, 0.05, 0.05))
    if not candidates:
        return [DEFAULT_COMPONENT_WEIGHTS]
    return candidates
