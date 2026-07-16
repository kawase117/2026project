from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.utils.theory_engine import load_hall_config, load_theory_frame, summarize_by  # noqa: E402
from eda.section_lateral_expansion import _load_coords  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "rakuen_durability_check"
DATA_START = pd.Timestamp("2025-01-01")
DATA_END = pd.Timestamp("2026-07-10")
MIN_GAMES = 2000
MIN_CELL_N = 5
LOW_ACTIVITY_Q = 0.20
EVENT_DDS = {10, 11, 22, 30}

HOT_SECTIONS = ["3164-3173", "3200-3225", "2141-2162"]
COLD_SECTIONS = ["1130-1134", "1106-1115", "3113-3116"]
EVENT_SECTIONS = ["1209-1216", "1057-1059"]
TYPE_A_SECTIONS = ["1106-1115", "1130-1134"]
TYPE_B_SECTIONS = [
    "3117-3120",
    "2000-2003",
    "2004-2007",
    "3107-3112",
    "1057-1059",
    "2111-2113",
    "2171-2172",
]
TYPE_B_META = {
    "3117-3120": {"target_dds": "11,29,30", "avoid_dds": "25,31,14"},
    "2000-2003": {"target_dds": "", "avoid_dds": ""},
    "2004-2007": {"target_dds": "", "avoid_dds": ""},
    "3107-3112": {"target_dds": "", "avoid_dds": ""},
    "1057-1059": {"target_dds": "", "avoid_dds": ""},
    "2111-2113": {"target_dds": "", "avoid_dds": ""},
    "2171-2172": {"target_dds": "", "avoid_dds": ""},
}
TYPE_A_META = {
    "1106-1115": {"label": "Type A", "note": "31 DD all negative in the theory note"},
    "1130-1134": {"label": "Type A", "note": "31 DD all negative in the theory note"},
}
EDGE_TARGETS = [
    {"target": "DD4@本館1F_N", "segment": "本館1F_N", "dd": 4, "note": "theory p=0.003, ε²=0.059"},
    {"target": "DD24@本館_A", "segment": "本館_A", "dd": 24, "note": "full pool non-significant in theory"},
    {"target": "DD25@本館2F_N", "segment": "本館2F_N", "dd": 25, "note": "theory p=0.030, ε²=0.009"},
    {"target": "DD27@本館_A", "segment": "本館_A", "dd": 27, "note": "reproduced in two segments in theory"},
    {"target": "DD3@新館_N", "segment": "新館_N", "dd": 3, "note": "theory reproduction"},
    {"target": "DD3@本館2F_N", "segment": "本館2F_N", "dd": 3, "note": "theory reproduction"},
]
SECTION_3113_SPLIT_POS = [19, 12, 4]
SECTION_3113_SPLIT_NEG = [18, 22, 6]


def _fmt(value: object, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return ""
        return f"{float(value):.{digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if pd.isna(value):
        return ""
    return str(value)


def _markdown_table(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 3) -> str:
    work = frame.copy()
    if columns is not None:
        work = work.loc[:, columns]
    if work.empty:
        return "No rows."
    headers = [str(col) for col in work.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in work.iterrows():
        lines.append("| " + " | ".join(_fmt(row[col], digits=float_digits) for col in work.columns) + " |")
    return "\n".join(lines)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _safe_kruskal(groups: list[pd.Series]) -> tuple[float, float, float]:
    valid_groups = [pd.to_numeric(group, errors="coerce").dropna() for group in groups]
    valid_groups = [group for group in valid_groups if len(group) >= MIN_CELL_N]
    if len(valid_groups) < 2:
        return float("nan"), float("nan"), float("nan")
    stat, p_value = kruskal(*valid_groups)
    n_total = int(sum(len(group) for group in valid_groups))
    epsilon_sq = float(stat / (n_total - 1)) if n_total > 1 else float("nan")
    return float(stat), float(p_value), epsilon_sq


def _sign(value: float) -> int:
    if pd.isna(value):
        return 0
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _direction_label(value: float) -> str:
    sign = _sign(value)
    if sign > 0:
        return "plus"
    if sign < 0:
        return "minus"
    return "flat"


def _classify_verdict(full_value: float, first_value: float, second_value: float) -> str:
    if pd.isna(full_value) or pd.isna(first_value) or pd.isna(second_value):
        return "消滅"
    full_sign = _sign(full_value)
    first_sign = _sign(first_value)
    second_sign = _sign(second_value)
    if full_sign == 0 or first_sign == 0 or second_sign == 0:
        return "消滅"
    if first_sign != full_sign or second_sign != full_sign:
        return "消滅"
    ratios = [abs(first_value) / abs(full_value), abs(second_value) / abs(full_value)]
    if min(ratios) >= 0.6:
        return "生存"
    if min(ratios) >= 0.25:
        return "弱化"
    return "消滅"


def _compare_single_verdict(full_value: float, alt_value: float) -> str:
    if pd.isna(full_value) or pd.isna(alt_value):
        return "消滅"
    full_sign = _sign(full_value)
    alt_sign = _sign(alt_value)
    if full_sign == 0 or alt_sign == 0 or alt_sign != full_sign:
        return "消滅"
    ratio = abs(alt_value) / abs(full_value)
    if ratio >= 0.6:
        return "生存"
    if ratio >= 0.25:
        return "弱化"
    return "消滅"


def _split_dates(dates: pd.Series) -> tuple[set[pd.Timestamp], set[pd.Timestamp], pd.Timestamp]:
    ordered = sorted(pd.Timestamp(value).normalize() for value in pd.Series(dates).dropna().unique())
    if not ordered:
        return set(), set(), pd.NaT
    midpoint = len(ordered) // 2
    first = set(ordered[:midpoint])
    second = set(ordered[midpoint:])
    boundary = ordered[midpoint - 1] if midpoint > 0 else ordered[0]
    return first, second, boundary


def _split_frame(frame: pd.DataFrame, dates: set[pd.Timestamp]) -> pd.DataFrame:
    if not dates:
        return frame.iloc[0:0].copy()
    return frame.loc[frame["date_dt"].isin(dates)].copy()


def _prepare_frame(db_path: Path) -> pd.DataFrame:
    raw = load_theory_frame(db_path)
    if raw.empty:
        raise ValueError(f"failed to load theory frame from {db_path}")

    work = raw.copy()
    work["date_dt"] = pd.to_datetime(work["date_dt"], errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["dd"] = pd.to_numeric(work["dd"], errors="coerce")
    work["hit104"] = pd.to_numeric(work["hit104"], errors="coerce")
    work = work.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized", "dd"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["dd"] = work["dd"].astype(int)
    work["segment"] = work["segment"].fillna("対象外").astype(str)
    work["is_event_day"] = work["is_event_day"].fillna(False).astype(bool)
    work = work.loc[work["date_dt"].between(DATA_START, DATA_END)].copy()
    work = work.loc[work["games_normalized"].ge(MIN_GAMES)].copy()
    return work.reset_index(drop=True)


def _low_activity_filter(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    daily = (
        frame.groupby("date_dt", as_index=False)
        .agg(total_games=("games_normalized", "sum"), row_count=("machine_number", "size"))
        .sort_values("date_dt")
        .reset_index(drop=True)
    )
    if daily.empty:
        return frame.copy(), daily, float("nan")
    cutoff = float(daily["total_games"].quantile(LOW_ACTIVITY_Q))
    low_dates = set(daily.loc[daily["total_games"].le(cutoff), "date_dt"])
    filtered = frame.loc[~frame["date_dt"].isin(low_dates)].copy()
    daily["is_low_activity"] = daily["date_dt"].isin(low_dates)
    daily["quantile_cutoff"] = cutoff
    return filtered.reset_index(drop=True), daily, cutoff


def _hall_rates(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {"win_rate": float("nan"), "hit104_rate": float("nan"), "avg_diff": float("nan")}
    return {
        "win_rate": float(pd.to_numeric(frame["diff_coins_normalized"], errors="coerce").gt(0).mean()),
        "hit104_rate": float(pd.to_numeric(frame["hit104"], errors="coerce").mean()),
        "avg_diff": float(pd.to_numeric(frame["diff_coins_normalized"], errors="coerce").mean()),
    }


def _summarize_sections(frame: pd.DataFrame, sections: list[str], *, min_n: int = 1) -> pd.DataFrame:
    work = frame.loc[frame["section"].isin(sections)].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "n",
                "avg_diff",
                "avg_games",
                "win_rate",
                "hit104_rate",
                "hall_win_rate",
                "hall_hit104_rate",
                "delta_win_pp",
                "delta_hit104_pp",
            ]
        )
    summary = summarize_by(work, ["section"], min_n=min_n).copy()
    if summary.empty:
        return summary
    hall = _hall_rates(work)
    summary["hall_win_rate"] = hall["win_rate"]
    summary["hall_hit104_rate"] = hall["hit104_rate"]
    summary["delta_win_pp"] = (summary["win_rate"] - hall["win_rate"]) * 100.0
    summary["delta_hit104_pp"] = (summary["hit104_rate"] - hall["hit104_rate"]) * 100.0
    return summary.sort_values(
        ["avg_diff", "delta_win_pp", "section"], ascending=[False, False, True], kind="mergesort"
    ).reset_index(drop=True)


def _event_summary(frame: pd.DataFrame, sections: list[str]) -> pd.DataFrame:
    work = frame.loc[frame["section"].isin(sections)].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "event_n",
                "non_event_n",
                "event_avg_diff",
                "non_event_avg_diff",
                "event_win_rate",
                "non_event_win_rate",
                "lift_pp",
                "avg_diff_gap",
                "event_share",
            ]
        )

    rows: list[dict[str, object]] = []
    for section, section_frame in work.groupby("section", sort=True):
        event = section_frame.loc[section_frame["is_event_day"]].copy()
        nonevent = section_frame.loc[~section_frame["is_event_day"]].copy()
        if event.empty or nonevent.empty:
            continue
        rows.append(
            {
                "section": section,
                "event_n": int(len(event)),
                "non_event_n": int(len(nonevent)),
                "event_avg_diff": float(event["diff_coins_normalized"].mean()),
                "non_event_avg_diff": float(nonevent["diff_coins_normalized"].mean()),
                "event_win_rate": float(event["diff_coins_normalized"].gt(0).mean()),
                "non_event_win_rate": float(nonevent["diff_coins_normalized"].gt(0).mean()),
                "lift_pp": float(
                    (event["diff_coins_normalized"].gt(0).mean() - nonevent["diff_coins_normalized"].gt(0).mean())
                    * 100.0
                ),
                "avg_diff_gap": float(event["diff_coins_normalized"].mean() - nonevent["diff_coins_normalized"].mean()),
                "event_share": float(len(event) / len(section_frame)),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(
        ["lift_pp", "avg_diff_gap", "section"], ascending=[False, False, True], kind="mergesort"
    ).reset_index(drop=True)


def _dd_curve(frame: pd.DataFrame, section: str) -> pd.DataFrame:
    work = frame.loc[frame["section"].eq(section)].copy()
    if work.empty:
        return pd.DataFrame(columns=["section", "dd", "n", "avg_diff", "win_rate", "hit104_rate"])
    summary = summarize_by(work, ["dd"], min_n=MIN_CELL_N).copy()
    if summary.empty:
        return pd.DataFrame(columns=["section", "dd", "n", "avg_diff", "win_rate", "hit104_rate"])
    summary["section"] = section
    summary["dd"] = summary["dd"].astype(int)
    summary["sign"] = summary["avg_diff"].map(_direction_label)
    summary["rank_high"] = summary["avg_diff"].rank(method="dense", ascending=False).astype(int)
    summary["rank_low"] = summary["avg_diff"].rank(method="dense", ascending=True).astype(int)
    return summary.sort_values(["dd"], kind="mergesort").reset_index(drop=True)


def _section_dd_metrics(frame: pd.DataFrame, section: str) -> dict[str, object]:
    section_frame = frame.loc[frame["section"].eq(section)].copy()
    curve = _dd_curve(frame, section)
    if section_frame.empty:
        return {
            "section": section,
            "n": 0,
            "avg_diff": float("nan"),
            "avg_games": float("nan"),
            "win_rate": float("nan"),
            "hit104_rate": float("nan"),
            "dd_valid_n": 0,
            "dd_swing": float("nan"),
            "positive_rate": float("nan"),
            "negative_rate": float("nan"),
            "dominant_sign_rate": float("nan"),
            "sign_change_count": 0,
            "best_dd": pd.NA,
            "best_dd_avg_diff": float("nan"),
            "worst_dd": pd.NA,
            "worst_dd_avg_diff": float("nan"),
            "kw_stat": float("nan"),
            "kw_p": float("nan"),
            "kw_epsilon_sq": float("nan"),
        }

    stats = summarize_by(section_frame, ["section"], min_n=1).iloc[0]
    dd_values = pd.to_numeric(curve["avg_diff"], errors="coerce").dropna()
    dd_list = dd_values.tolist()
    pos_rate = float((dd_values > 0).mean()) if len(dd_values) else float("nan")
    neg_rate = float((dd_values < 0).mean()) if len(dd_values) else float("nan")
    dominant = float(max(pos_rate, neg_rate)) if len(dd_values) else float("nan")
    sign_change_count = 0
    compact = [1 if value > 0 else -1 if value < 0 else 0 for value in dd_list]
    compact = [value for value in compact if value != 0]
    if len(compact) >= 2:
        sign_change_count = int(sum(left != right for left, right in zip(compact, compact[1:])))

    if curve.empty:
        best_dd = pd.NA
        best_dd_avg_diff = float("nan")
        worst_dd = pd.NA
        worst_dd_avg_diff = float("nan")
        swing = float("nan")
    else:
        best_row = curve.sort_values(
            ["avg_diff", "win_rate", "n", "dd"], ascending=[False, False, False, True], kind="mergesort"
        ).iloc[0]
        worst_row = curve.sort_values(
            ["avg_diff", "win_rate", "n", "dd"], ascending=[True, True, False, True], kind="mergesort"
        ).iloc[0]
        best_dd = int(best_row["dd"])
        best_dd_avg_diff = float(best_row["avg_diff"])
        worst_dd = int(worst_row["dd"])
        worst_dd_avg_diff = float(worst_row["avg_diff"])
        swing = float(best_dd_avg_diff - worst_dd_avg_diff)

    groups = [
        pd.to_numeric(group["diff_coins_normalized"], errors="coerce").dropna()
        for _, group in section_frame.groupby("dd", dropna=False)
    ]
    kw_stat, kw_p, kw_eps = _safe_kruskal(groups)

    return {
        "section": section,
        "n": int(stats["n"]),
        "avg_diff": float(stats["avg_diff"]),
        "avg_games": float(stats["avg_games"]),
        "win_rate": float(stats["win_rate"]),
        "hit104_rate": float(stats["hit104_rate"]),
        "dd_valid_n": int(len(curve)),
        "dd_swing": swing,
        "positive_rate": pos_rate,
        "negative_rate": neg_rate,
        "dominant_sign_rate": dominant,
        "sign_change_count": int(sign_change_count),
        "best_dd": best_dd,
        "best_dd_avg_diff": best_dd_avg_diff,
        "worst_dd": worst_dd,
        "worst_dd_avg_diff": worst_dd_avg_diff,
        "kw_stat": kw_stat,
        "kw_p": kw_p,
        "kw_epsilon_sq": kw_eps,
    }


def _section_dd_table(frame: pd.DataFrame, sections: list[str], *, period: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for section in sections:
        metrics = _section_dd_metrics(frame, section)
        curve = _dd_curve(frame, section)
        rows.append(
            {
                "record_type": "section_summary",
                "period": period,
                **metrics,
            }
        )
        if section == "3113-3116" and not curve.empty:
            for dd, group in curve.groupby("dd", sort=True):
                rows.append(
                    {
                        "record_type": "dd_detail",
                        "period": period,
                        "section": section,
                        "dd": int(dd),
                        "n": int(group["n"].iloc[0]),
                        "avg_diff": float(group["avg_diff"].iloc[0]),
                        "win_rate": float(group["win_rate"].iloc[0]),
                        "hit104_rate": float(group["hit104_rate"].iloc[0]),
                        "sign": str(group["sign"].iloc[0]),
                        "rank_high": int(group["rank_high"].iloc[0]),
                        "rank_low": int(group["rank_low"].iloc[0]),
                    }
                )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(
        ["record_type", "section", "period", "dd"],
        ascending=[True, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _segment_kw(frame: pd.DataFrame, segment: str, *, period: str) -> dict[str, object]:
    section_frame = frame.loc[frame["segment"].eq(segment)].copy()
    if section_frame.empty:
        return {
            "record_type": "segment_kw",
            "period": period,
            "segment": segment,
            "segment_n": 0,
            "segment_avg_diff": float("nan"),
            "segment_win_rate": float("nan"),
            "segment_hit104_rate": float("nan"),
            "dd_valid_n": 0,
            "kw_stat": float("nan"),
            "kw_p": float("nan"),
            "kw_epsilon_sq": float("nan"),
            "best_dd": pd.NA,
            "best_dd_avg_diff": float("nan"),
            "worst_dd": pd.NA,
            "worst_dd_avg_diff": float("nan"),
        }
    segment_stats = summarize_by(section_frame, ["section"], min_n=1)
    section_summary = _hall_rates(section_frame)
    curve = summarize_by(section_frame, ["dd"], min_n=MIN_CELL_N).copy()
    if curve.empty:
        best_dd = pd.NA
        best_dd_avg_diff = float("nan")
        worst_dd = pd.NA
        worst_dd_avg_diff = float("nan")
    else:
        best_row = curve.sort_values(
            ["avg_diff", "win_rate", "n", "dd"], ascending=[False, False, False, True], kind="mergesort"
        ).iloc[0]
        worst_row = curve.sort_values(
            ["avg_diff", "win_rate", "n", "dd"], ascending=[True, True, False, True], kind="mergesort"
        ).iloc[0]
        best_dd = int(best_row["dd"])
        best_dd_avg_diff = float(best_row["avg_diff"])
        worst_dd = int(worst_row["dd"])
        worst_dd_avg_diff = float(worst_row["avg_diff"])

    groups = [
        pd.to_numeric(group["diff_coins_normalized"], errors="coerce").dropna()
        for _, group in section_frame.groupby("dd", dropna=False)
    ]
    kw_stat, kw_p, kw_eps = _safe_kruskal(groups)
    return {
        "record_type": "segment_kw",
        "period": period,
        "segment": segment,
        "segment_n": int(len(section_frame)),
        "segment_avg_diff": float(section_frame["diff_coins_normalized"].mean()),
        "segment_win_rate": float(section_frame["diff_coins_normalized"].gt(0).mean()),
        "segment_hit104_rate": float(section_frame["hit104"].mean()),
        "dd_valid_n": int(len(curve)),
        "kw_stat": kw_stat,
        "kw_p": kw_p,
        "kw_epsilon_sq": kw_eps,
        "best_dd": best_dd,
        "best_dd_avg_diff": best_dd_avg_diff,
        "worst_dd": worst_dd,
        "worst_dd_avg_diff": worst_dd_avg_diff,
    }


def _edge_target_rows(frame: pd.DataFrame, *, period: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for target in EDGE_TARGETS:
        segment = target["segment"]
        dd = int(target["dd"])
        segment_frame = frame.loc[frame["segment"].eq(segment)].copy()
        dd_frame = segment_frame.loc[segment_frame["dd"].eq(dd)].copy()
        summary = _segment_kw(frame, segment, period=period)
        dd_rank = float("nan")
        if not segment_frame.empty:
            dd_curve = summarize_by(segment_frame, ["dd"], min_n=MIN_CELL_N).copy()
            if not dd_curve.empty:
                dd_curve = dd_curve.sort_values(
                    ["avg_diff", "win_rate", "n", "dd"], ascending=[False, False, False, True], kind="mergesort"
                ).reset_index(drop=True)
                dd_curve["rank_high"] = np.arange(1, len(dd_curve) + 1)
                dd_curve["rank_low"] = np.arange(len(dd_curve), 0, -1)
                match = dd_curve.loc[dd_curve["dd"].eq(dd)]
                if not match.empty:
                    dd_rank = float(match["rank_high"].iloc[0])
        rows.append(
            {
                "record_type": "target_dd",
                "period": period,
                "target": target["target"],
                "segment": segment,
                "dd": dd,
                "n": int(len(dd_frame)),
                "avg_diff": float(dd_frame["diff_coins_normalized"].mean()) if not dd_frame.empty else float("nan"),
                "win_rate": float(dd_frame["diff_coins_normalized"].gt(0).mean())
                if not dd_frame.empty
                else float("nan"),
                "hit104_rate": float(dd_frame["hit104"].mean()) if not dd_frame.empty else float("nan"),
                "rank_high": dd_rank,
                "segment_kw_p": float(summary["kw_p"]),
                "segment_kw_epsilon_sq": float(summary["kw_epsilon_sq"]),
                "segment_best_dd": summary["best_dd"],
                "segment_worst_dd": summary["worst_dd"],
                "note": target["note"],
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["target", "period"], kind="mergesort").reset_index(drop=True)


def _low_activity_summary(full_frame: pd.DataFrame, filtered_frame: pd.DataFrame) -> pd.DataFrame:
    sections = HOT_SECTIONS + COLD_SECTIONS + EVENT_SECTIONS + TYPE_A_SECTIONS + TYPE_B_SECTIONS + ["3113-3116"]
    records: list[dict[str, object]] = []

    def _compare_item(group: str, item: str, full_value: float, filtered_value: float) -> dict[str, object]:
        delta = filtered_value - full_value
        return {
            "analysis_group": group,
            "item": item,
            "full_value": full_value,
            "low_activity_value": filtered_value,
            "delta": delta,
            "direction_full": _direction_label(full_value),
            "direction_low_activity": _direction_label(filtered_value),
            "verdict": _compare_single_verdict(full_value, filtered_value),
        }

    full_hc = _summarize_sections(full_frame, HOT_SECTIONS + COLD_SECTIONS)
    low_hc = _summarize_sections(filtered_frame, HOT_SECTIONS + COLD_SECTIONS)
    for section in HOT_SECTIONS + COLD_SECTIONS:
        full_row = full_hc.loc[full_hc["section"].eq(section)]
        low_row = low_hc.loc[low_hc["section"].eq(section)]
        if full_row.empty or low_row.empty:
            continue
        full_value = float(full_row["delta_hit104_pp"].iloc[0])
        low_value = float(low_row["delta_hit104_pp"].iloc[0])
        records.append(_compare_item("hotcold", section, full_value, low_value))

    full_event = _event_summary(full_frame, EVENT_SECTIONS)
    low_event = _event_summary(filtered_frame, EVENT_SECTIONS)
    for section in EVENT_SECTIONS:
        full_row = full_event.loc[full_event["section"].eq(section)]
        low_row = low_event.loc[low_event["section"].eq(section)]
        if full_row.empty or low_row.empty:
            continue
        full_value = float(full_row["lift_pp"].iloc[0])
        low_value = float(low_row["lift_pp"].iloc[0])
        records.append(_compare_item("event", section, full_value, low_value))

    full_type = _section_table_for_type(full_frame)
    low_type = _section_table_for_type(filtered_frame)
    for section in full_type["section"].unique().tolist():
        full_row = full_type.loc[full_type["section"].eq(section) & full_type["record_type"].eq("section_summary")]
        low_row = low_type.loc[low_type["section"].eq(section) & low_type["record_type"].eq("section_summary")]
        if full_row.empty or low_row.empty:
            continue
        full_value = float(full_row["avg_diff"].iloc[0])
        low_value = float(low_row["avg_diff"].iloc[0])
        records.append(_compare_item("type_ab", section, full_value, low_value))

    full_edge = _edge_target_rows(full_frame, period="full")
    low_edge = _edge_target_rows(filtered_frame, period="low_activity")
    for target in full_edge["target"].unique().tolist():
        full_row = full_edge.loc[full_edge["target"].eq(target)]
        low_row = low_edge.loc[low_edge["target"].eq(target)]
        if full_row.empty or low_row.empty:
            continue
        full_value = float(full_row["avg_diff"].iloc[0])
        low_value = float(low_row["avg_diff"].iloc[0])
        records.append(_compare_item("edge", target, full_value, low_value))

    out = pd.DataFrame(records)
    if out.empty:
        return out
    return out.sort_values(["analysis_group", "item"], kind="mergesort").reset_index(drop=True)


def _section_table_for_type(frame: pd.DataFrame) -> pd.DataFrame:
    sections = TYPE_A_SECTIONS + TYPE_B_SECTIONS + ["3113-3116"]
    rows: list[dict[str, object]] = []
    for section in sections:
        metrics = _section_dd_metrics(frame, section)
        meta = TYPE_A_META.get(section) or TYPE_B_META.get(section) or {}
        rows.append(
            {
                "record_type": "section_summary",
                "section": section,
                **meta,
                **metrics,
            }
        )
        if section == "3113-3116":
            curve = _dd_curve(frame, section)
            for dd, dd_row in curve.iterrows():
                dd_value = int(dd_row["dd"])
                theory_group = (
                    "plus"
                    if dd_value in SECTION_3113_SPLIT_POS
                    else "minus"
                    if dd_value in SECTION_3113_SPLIT_NEG
                    else "neutral"
                )
                rows.append(
                    {
                        "record_type": "dd_detail",
                        "section": section,
                        "dd": dd_value,
                        "avg_diff": float(dd_row["avg_diff"]),
                        "sign": str(dd_row["sign"]),
                        "theory_group": theory_group,
                        "rank_high": int(dd_row["rank_high"]),
                        "rank_low": int(dd_row["rank_low"]),
                        "note": "full positive/negative DD partition for split-half swap check",
                    }
                )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["record_type", "section", "dd"], kind="mergesort").reset_index(drop=True)


def _build_report(
    *,
    db_path: Path,
    frame: pd.DataFrame,
    split_boundary: pd.Timestamp,
    low_activity_cutoff: float,
    low_activity_daily: pd.DataFrame,
    hotcold: pd.DataFrame,
    event: pd.DataFrame,
    type_table: pd.DataFrame,
    edge: pd.DataFrame,
    low_activity: pd.DataFrame,
) -> str:
    first_rows = len(frame.loc[frame["date_dt"].le(split_boundary)])
    second_rows = len(frame.loc[frame["date_dt"].gt(split_boundary)])
    lines: list[str] = []
    lines.append("# 楽園蒲田店 耐久性検証")
    lines.append("")
    lines.append("## 1. 手法概要")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- 対象期間: {frame['date_dt'].min().date()} 〜 {frame['date_dt'].max().date()}")
    lines.append(f"- min_games: `{MIN_GAMES}`")
    lines.append(f"- split-half 境界: `{split_boundary.date()}`")
    lines.append(f"- split-half 件数: first={first_rows:,}, second={second_rows:,}")
    lines.append(f"- 低稼働日除外: 日次総gamesの下位 `{int(LOW_ACTIVITY_Q * 100)}%` を除外")
    lines.append(f"- 低稼働日カットオフ: `{low_activity_cutoff:,.1f}`")
    lines.append(
        f"- 低稼働日除外の対象日数: `{int(low_activity_daily['is_low_activity'].sum())}` / `{len(low_activity_daily)}`"
    )
    lines.append(f"- イベント日定義: `{{10, 11, 22, 30}}` + 強ゾロ目")
    lines.append(
        f"- 分類基準: 同方向維持を前提に、効果が `>=60%` なら `生存`、`>=25%` なら `弱化`、それ未満または反転は `消滅`"
    )
    lines.append("")

    lines.append("## 2. Hot/Coldセクションのsplit-half結果")
    hotcold_display = hotcold.loc[
        :,
        [
            "group",
            "section",
            "period",
            "n",
            "avg_diff",
            "win_rate",
            "hit104_rate",
            "delta_win_pp",
            "delta_hit104_pp",
            "verdict",
        ],
    ].copy()
    lines.append(_markdown_table(hotcold_display, float_digits=3))
    lines.append("")

    lines.append("## 3. Event-responsiveセクションのsplit-half結果")
    event_display = event.loc[
        :,
        [
            "section",
            "period",
            "event_n",
            "non_event_n",
            "event_avg_diff",
            "non_event_avg_diff",
            "event_win_rate",
            "non_event_win_rate",
            "lift_pp",
            "avg_diff_gap",
            "verdict",
        ],
    ].copy()
    lines.append(_markdown_table(event_display, float_digits=3))
    lines.append("")

    lines.append("## 4. Type A/Bセクションのsplit-half結果（3113-3116を重点的に）")
    type_summary = type_table.loc[type_table["record_type"].eq("section_summary")].copy()
    type_display = type_summary.loc[
        :,
        [
            "section",
            "label",
            "period",
            "n",
            "avg_diff",
            "win_rate",
            "hit104_rate",
            "dd_valid_n",
            "dd_swing",
            "dominant_sign_rate",
            "sign_change_count",
            "best_dd",
            "worst_dd",
            "kw_p",
            "kw_epsilon_sq",
            "verdict",
            "target_dds",
            "avoid_dds",
            "note",
        ],
    ].copy()
    lines.append(_markdown_table(type_display, float_digits=3))
    lines.append("")
    type_detail = type_table.loc[
        type_table["record_type"].eq("dd_detail") & type_table["section"].eq("3113-3116")
    ].copy()
    if not type_detail.empty:
        lines.append("### 3113-3116 DD detail")
        lines.append(
            _markdown_table(
                type_detail.loc[:, ["period", "dd", "avg_diff", "sign", "rank_high", "rank_low"]], float_digits=3
            )
        )
        lines.append("")
        focus = type_detail.loc[type_detail["theory_group"].isin(["plus", "minus"])].copy()
        if not focus.empty:
            lines.append("### 3113-3116 plus/minus focus")
            lines.append(
                _markdown_table(
                    focus.loc[
                        :, ["period", "dd", "theory_group", "avg_diff", "sign", "rank_high", "rank_low", "verdict"]
                    ],
                    float_digits=3,
                )
            )
            lines.append("")

    lines.append("## 5. 端番セグメント別発見のsplit-half結果")
    edge_display = edge.loc[
        :,
        [
            "target",
            "segment",
            "dd",
            "period",
            "n",
            "avg_diff",
            "win_rate",
            "hit104_rate",
            "rank_high",
            "segment_kw_p",
            "segment_kw_epsilon_sq",
            "segment_best_dd",
            "segment_worst_dd",
            "verdict",
            "note",
        ],
    ].copy()
    lines.append(_markdown_table(edge_display, float_digits=3))
    lines.append("")

    lines.append("## 6. 低稼働日除外の影響")
    low_display = low_activity.loc[
        :,
        [
            "analysis_group",
            "item",
            "full_value",
            "low_activity_value",
            "delta",
            "direction_full",
            "direction_low_activity",
            "verdict",
        ],
    ].copy()
    lines.append(_markdown_table(low_display, float_digits=3))
    lines.append("")

    lines.append("## 7. 総括（生存/弱化/消滅の一覧表）")
    summary_rows = []

    def _append_group(group_name: str, table: pd.DataFrame, key_col: str, *, record_type: str | None = None) -> None:
        if table.empty or key_col not in table.columns:
            return
        work = table.copy()
        if record_type is not None and "record_type" in work.columns:
            work = work.loc[work["record_type"].eq(record_type)].copy()
        if work.empty:
            return
        for item, rows in work.groupby(key_col, dropna=False):
            verdicts = [
                str(value) for value in rows.get("verdict", pd.Series(dtype=object)).dropna().tolist() if str(value)
            ]
            verdicts = [value for value in verdicts if value]
            if not verdicts:
                continue
            summary_rows.append({"group": group_name, "item": item, "verdict": verdicts[0]})

    _append_group("Hot/Cold", hotcold, "section")
    _append_group("Event-responsive", event, "section")
    _append_group("Type A/B", type_summary, "section", record_type="section_summary")
    _append_group("Edge targets", edge, "target")
    _append_group("Low-activity", low_activity, "item")
    summary_table = pd.DataFrame(summary_rows).drop_duplicates().sort_values(["group", "item"], kind="mergesort")
    lines.append(_markdown_table(summary_table, float_digits=3))
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_outputs(db_path: Path, output_dir: Path) -> dict[str, pd.DataFrame]:
    config = load_hall_config("rakuen")
    if not config:
        raise ValueError("rakuen hall config is missing or invalid")

    frame = _prepare_frame(db_path)
    if frame.empty:
        raise ValueError("no rows remained after filtering")

    low_activity_frame, low_daily, low_cutoff = _low_activity_filter(frame)
    first_dates, second_dates, split_boundary = _split_dates(frame["date_dt"])
    first_frame = _split_frame(frame, first_dates)
    second_frame = _split_frame(frame, second_dates)

    hotcold_rows = []
    for period, period_frame in [("full", frame), ("first_half", first_frame), ("second_half", second_frame)]:
        summary = _summarize_sections(period_frame, HOT_SECTIONS + COLD_SECTIONS)
        if summary.empty:
            continue
        for group_name, section_list in [("Hot", HOT_SECTIONS), ("Cold", COLD_SECTIONS)]:
            scoped = summary.loc[summary["section"].isin(section_list)].copy()
            for _, row in scoped.iterrows():
                hotcold_rows.append(
                    {
                        "record_type": "section_summary",
                        "group": group_name,
                        "section": row["section"],
                        "period": period,
                        "n": int(row["n"]),
                        "avg_diff": float(row["avg_diff"]),
                        "win_rate": float(row["win_rate"]),
                        "hit104_rate": float(row["hit104_rate"]),
                        "delta_win_pp": float(row["delta_win_pp"]),
                        "delta_hit104_pp": float(row["delta_hit104_pp"]),
                        "verdict": "",
                    }
                )
    hotcold = pd.DataFrame(hotcold_rows)
    if not hotcold.empty:
        hotcold = hotcold.sort_values(["group", "period", "section"], kind="mergesort").reset_index(drop=True)
        for section in HOT_SECTIONS + COLD_SECTIONS:
            rows = hotcold.loc[hotcold["section"].eq(section)].copy()
            if rows.empty:
                continue
            if not {"full", "first_half", "second_half"}.issubset(set(rows["period"].astype(str))):
                continue
            full_value = float(rows.loc[rows["period"].eq("full"), "delta_hit104_pp"].iloc[0])
            first_value = float(rows.loc[rows["period"].eq("first_half"), "delta_hit104_pp"].iloc[0])
            second_value = float(rows.loc[rows["period"].eq("second_half"), "delta_hit104_pp"].iloc[0])
            hotcold.loc[hotcold["section"].eq(section), "verdict"] = _classify_verdict(
                full_value, first_value, second_value
            )

    event_rows = []
    for period, period_frame in [("full", frame), ("first_half", first_frame), ("second_half", second_frame)]:
        summary = _event_summary(period_frame, EVENT_SECTIONS)
        if summary.empty:
            continue
        for _, row in summary.iterrows():
            event_rows.append(
                {
                    "record_type": "section_summary",
                    "section": row["section"],
                    "period": period,
                    "event_n": int(row["event_n"]),
                    "non_event_n": int(row["non_event_n"]),
                    "event_avg_diff": float(row["event_avg_diff"]),
                    "non_event_avg_diff": float(row["non_event_avg_diff"]),
                    "event_win_rate": float(row["event_win_rate"]),
                    "non_event_win_rate": float(row["non_event_win_rate"]),
                    "lift_pp": float(row["lift_pp"]),
                    "avg_diff_gap": float(row["avg_diff_gap"]),
                    "event_share": float(row["event_share"]),
                    "verdict": "",
                }
            )
    event = pd.DataFrame(event_rows)
    if not event.empty:
        event = event.sort_values(["section", "period"], kind="mergesort").reset_index(drop=True)
        for section in EVENT_SECTIONS:
            rows = event.loc[event["section"].eq(section)]
            if rows.empty:
                continue
            if not {"full", "first_half", "second_half"}.issubset(set(rows["period"].astype(str))):
                continue
            full_value = float(rows.loc[rows["period"].eq("full"), "lift_pp"].iloc[0])
            first_value = float(rows.loc[rows["period"].eq("first_half"), "lift_pp"].iloc[0])
            second_value = float(rows.loc[rows["period"].eq("second_half"), "lift_pp"].iloc[0])
            event.loc[event["section"].eq(section), "verdict"] = _classify_verdict(
                full_value, first_value, second_value
            )

    type_rows = []
    type_period_frames = [("full", frame), ("first_half", first_frame), ("second_half", second_frame)]
    for period, period_frame in type_period_frames:
        table = _section_table_for_type(period_frame)
        if table.empty:
            continue
        for _, row in table.loc[table["record_type"].eq("section_summary")].iterrows():
            type_rows.append({**row.to_dict(), "period": period})
        for _, row in table.loc[table["record_type"].eq("dd_detail")].iterrows():
            type_rows.append({**row.to_dict(), "period": period})
    type_table = pd.DataFrame(type_rows)
    if not type_table.empty:
        type_table = type_table.sort_values(["record_type", "section", "period", "dd"], kind="mergesort").reset_index(
            drop=True
        )
        for section in TYPE_A_SECTIONS + TYPE_B_SECTIONS + ["3113-3116"]:
            rows = type_table.loc[type_table["record_type"].eq("section_summary") & type_table["section"].eq(section)]
            if rows.empty:
                continue
            if not {"full", "first_half", "second_half"}.issubset(set(rows["period"].astype(str))):
                continue
            full_row = rows.loc[rows["period"].eq("full")]
            first_row = rows.loc[rows["period"].eq("first_half")]
            second_row = rows.loc[rows["period"].eq("second_half")]
            if full_row.empty or first_row.empty or second_row.empty:
                continue
            full_value = float(full_row["avg_diff"].iloc[0])
            first_value = float(first_row["avg_diff"].iloc[0])
            second_value = float(second_row["avg_diff"].iloc[0])
            verdict = _classify_verdict(full_value, first_value, second_value)
            type_table.loc[
                type_table["record_type"].eq("section_summary") & type_table["section"].eq(section), "verdict"
            ] = verdict
        # 3113-3116 DD rows: compare positive/negative DD sign stability
        dd_rows = type_table.loc[
            type_table["record_type"].eq("dd_detail") & type_table["section"].eq("3113-3116")
        ].copy()
        if not dd_rows.empty:
            for dd in sorted(dd_rows["dd"].dropna().astype(int).unique().tolist()):
                subset = dd_rows.loc[dd_rows["dd"].eq(dd)]
                if subset.empty:
                    continue
                if not {"full", "first_half", "second_half"}.issubset(set(subset["period"].astype(str))):
                    continue
                full_value = float(subset.loc[subset["period"].eq("full"), "avg_diff"].iloc[0])
                first_value = float(subset.loc[subset["period"].eq("first_half"), "avg_diff"].iloc[0])
                second_value = float(subset.loc[subset["period"].eq("second_half"), "avg_diff"].iloc[0])
                verdict = _classify_verdict(full_value, first_value, second_value)
                type_table.loc[
                    type_table["record_type"].eq("dd_detail")
                    & type_table["section"].eq("3113-3116")
                    & type_table["dd"].eq(dd),
                    "verdict",
                ] = verdict

    edge_rows = []
    for period, period_frame in type_period_frames:
        edge_rows.append(_edge_target_rows(period_frame, period=period))
    edge = pd.concat(edge_rows, ignore_index=True) if edge_rows else pd.DataFrame()
    if not edge.empty:
        edge = edge.sort_values(["target", "period"], kind="mergesort").reset_index(drop=True)
        for target in edge["target"].dropna().unique().tolist():
            rows = edge.loc[edge["target"].eq(target)]
            if rows.empty:
                continue
            if not {"full", "first_half", "second_half"}.issubset(set(rows["period"].astype(str))):
                continue
            full_value = float(rows.loc[rows["period"].eq("full"), "avg_diff"].iloc[0])
            first_value = float(rows.loc[rows["period"].eq("first_half"), "avg_diff"].iloc[0])
            second_value = float(rows.loc[rows["period"].eq("second_half"), "avg_diff"].iloc[0])
            edge.loc[edge["target"].eq(target), "verdict"] = _classify_verdict(full_value, first_value, second_value)

    low_activity = _low_activity_summary(frame, low_activity_frame)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(hotcold, output_dir / "hotcold_splithalf.csv")
    _write_csv(event, output_dir / "event_responsive_splithalf.csv")
    _write_csv(type_table, output_dir / "type_ab_splithalf.csv")
    _write_csv(edge, output_dir / "hanaban_segment_splithalf.csv")
    _write_csv(low_activity, output_dir / "low_activity_excluded.csv")

    report = _build_report(
        db_path=db_path,
        frame=frame,
        split_boundary=split_boundary,
        low_activity_cutoff=low_cutoff,
        low_activity_daily=low_daily,
        hotcold=hotcold,
        event=event,
        type_table=type_table,
        edge=edge,
        low_activity=low_activity,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return {
        "frame": frame,
        "split_boundary": pd.DataFrame({"split_boundary": [split_boundary]}),
        "hotcold": hotcold,
        "event": event,
        "type_table": type_table,
        "edge": edge,
        "low_activity": low_activity,
        "low_daily": low_daily,
    }


def main() -> int:
    db_path = DEFAULT_DB_PATH.resolve()
    output_dir = DEFAULT_OUTPUT_DIR.resolve()
    if not db_path.exists():
        print(f"[ERROR] db not found: {db_path}")
        return 1

    outputs = build_outputs(db_path, output_dir)
    frame = outputs["frame"]
    low_daily = outputs["low_daily"]
    split_boundary = outputs["split_boundary"].iloc[0]["split_boundary"]

    print(f"[OK] db: {db_path}")
    print(f"[OK] rows after filter: {len(frame):,}")
    print(f"[OK] date range: {frame['date_dt'].min().date()} -> {frame['date_dt'].max().date()}")
    print(f"[OK] split boundary: {split_boundary.date() if pd.notna(split_boundary) else 'n/a'}")
    print(f"[OK] low-activity cutoff: {float(low_daily['quantile_cutoff'].iloc[0]):,.1f}")
    print(f"[OK] low-activity excluded days: {int(low_daily['is_low_activity'].sum())}/{len(low_daily)}")
    for name in [
        "hotcold_splithalf.csv",
        "event_responsive_splithalf.csv",
        "type_ab_splithalf.csv",
        "hanaban_segment_splithalf.csv",
        "low_activity_excluded.csv",
        "report.md",
    ]:
        print(f"[OK] generated: {output_dir / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
