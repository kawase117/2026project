from __future__ import annotations

import argparse
import math
import sqlite3
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from scipy.stats import spearmanr


DB_PATH = Path("db/poco_analysis.db")
DEFAULT_HALLS = ("K1", "K7")
SIGNIFICANCE_R = 0.37
SIGNIFICANCE_P = 0.1


@dataclass(frozen=True)
class HallRow:
    hall: str
    date: str
    dd: int
    digits_list: list[int]
    first_digit: int
    dd_mod10: int
    prev_first_digit: int | None
    week_diff: int | None
    recent_freq: dict[int, int]


@dataclass(frozen=True)
class SignalSummary:
    x2_best_digit: int | None
    x2_best_r: float
    x2_best_p: float
    x3_r: float
    x3_p: float
    x4_best_offset: int
    x4_best_r: float
    x4_best_p: float
    x5_best_negative_r: float
    x5_best_negative_p: float
    x5_best_positive_r: float
    x5_best_positive_p: float
    x2_by_digit: dict[int, tuple[float, float]] = field(default_factory=dict)
    x4_by_offset: dict[int, tuple[float, float]] = field(default_factory=dict)
    x5_by_digit: dict[int, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionResult:
    hall: str
    date: str
    actual_digits: list[int]
    top3_pred: list[int]
    hit: bool
    reciprocal_rank: float
    score_map: dict[int, float]
    active_signals: list[str]


def parse_strategy_digits(value: str | None) -> list[int]:
    if not value:
        return []

    head = value.split("|", 1)[0].strip()
    if not head:
        return []

    digits: list[int] = []
    for token in head.split(","):
        part = token.strip()
        if not part:
            continue
        digit = int(part)
        if digit < 0 or digit > 9:
            raise ValueError(f"digit out of range: {digit}")
        digits.append(digit)
    return digits


def prepare_hall_rows(records: Iterable[dict[str, object]]) -> list[HallRow]:
    prepared: list[HallRow] = []
    history: list[HallRow] = []

    for record in records:
        digits_list = parse_strategy_digits(str(record["strategy_digits"]))
        if not digits_list:
            continue

        first_digit = digits_list[0]
        prev_first_digit = history[-1].first_digit if history else None
        week_diff = (
            (first_digit - prev_first_digit) % 10
            if prev_first_digit is not None
            else None
        )

        recent_freq = {digit: 0 for digit in range(10)}
        for prior_row in history[-4:]:
            seen_digits = set(prior_row.digits_list)
            for digit in seen_digits:
                recent_freq[digit] += 1

        row = HallRow(
            hall=str(record["hall"]),
            date=str(record["date"]),
            dd=int(record["dd"]),
            digits_list=digits_list,
            first_digit=first_digit,
            dd_mod10=int(record["dd"]) % 10,
            prev_first_digit=prev_first_digit,
            week_diff=week_diff,
            recent_freq=recent_freq,
        )
        prepared.append(row)
        history.append(row)

    return prepared


def load_hall_rows(db_path: Path, hall: str) -> list[HallRow]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT hall, date, dd, strategy_digits
            FROM poco_announcements
            WHERE weekday_jp = '土'
              AND strategy_type = '並び'
              AND strategy_digits IS NOT NULL
              AND hall = ?
            ORDER BY hall, date
            """,
            (hall,),
        ).fetchall()
    finally:
        conn.close()

    return prepare_hall_rows([dict(row) for row in rows])


def safe_spearman(x_values: list[int], y_values: list[int]) -> tuple[float, float]:
    if len(x_values) < 2 or len(y_values) < 2:
        return math.nan, math.nan

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = spearmanr(x_values, y_values)
    return float(result.statistic), float(result.pvalue)


def is_significant(r_value: float, p_value: float) -> bool:
    if math.isnan(r_value) or math.isnan(p_value):
        return False
    return abs(r_value) > SIGNIFICANCE_R and p_value < SIGNIFICANCE_P


def compute_signal_summary(rows: list[HallRow]) -> SignalSummary:
    x2_by_digit: dict[int, tuple[float, float]] = {}
    for digit in range(10):
        x_values = [row.dd_mod10 for row in rows]
        y_values = [1 if digit in row.digits_list else 0 for row in rows]
        x2_by_digit[digit] = safe_spearman(x_values, y_values)

    x2_best_digit = max(
        range(10),
        key=lambda digit: (
            _nan_safe_value(x2_by_digit[digit][0], negative_inf=True),
            -x2_by_digit[digit][1] if not math.isnan(x2_by_digit[digit][1]) else float("-inf"),
            digit,
        ),
    )
    x2_best_r, x2_best_p = x2_by_digit[x2_best_digit]

    eligible_rows = [row for row in rows if row.prev_first_digit is not None]
    x3_r, x3_p = safe_spearman(
        [row.prev_first_digit for row in eligible_rows if row.prev_first_digit is not None],
        [row.first_digit for row in eligible_rows],
    )

    x4_by_offset: dict[int, tuple[float, float]] = {}
    for offset in range(10):
        x_values = [
            ((row.prev_first_digit or 0) + offset) % 10
            for row in eligible_rows
        ]
        y_values = [row.first_digit for row in eligible_rows]
        x4_by_offset[offset] = safe_spearman(x_values, y_values)

    x4_best_offset = max(
        range(10),
        key=lambda offset: (
            _nan_safe_value(x4_by_offset[offset][0], negative_inf=True),
            -x4_by_offset[offset][1] if not math.isnan(x4_by_offset[offset][1]) else float("-inf"),
            -offset,
        ),
    )
    x4_best_r, x4_best_p = x4_by_offset[x4_best_offset]

    x5_by_digit: dict[int, tuple[float, float]] = {}
    for digit in range(10):
        x_values = [row.recent_freq[digit] for row in rows]
        y_values = [1 if digit in row.digits_list else 0 for row in rows]
        x5_by_digit[digit] = safe_spearman(x_values, y_values)

    x5_best_digit = min(
        range(10),
        key=lambda digit: (
            _nan_safe_value(x5_by_digit[digit][0], negative_inf=False),
            x5_by_digit[digit][1] if not math.isnan(x5_by_digit[digit][1]) else float("inf"),
            digit,
        ),
    )
    x5_best_negative_r, x5_best_negative_p = x5_by_digit[x5_best_digit]
    x5_mom_digit = max(
        range(10),
        key=lambda digit: (
            _nan_safe_value(x5_by_digit[digit][0], negative_inf=True),
            -x5_by_digit[digit][1] if not math.isnan(x5_by_digit[digit][1]) else float("-inf"),
            digit,
        ),
    )
    x5_best_positive_r, x5_best_positive_p = x5_by_digit[x5_mom_digit]

    return SignalSummary(
        x2_best_digit=x2_best_digit,
        x2_best_r=x2_best_r,
        x2_best_p=x2_best_p,
        x3_r=x3_r,
        x3_p=x3_p,
        x4_best_offset=x4_best_offset,
        x4_best_r=x4_best_r,
        x4_best_p=x4_best_p,
        x5_best_negative_r=x5_best_negative_r,
        x5_best_negative_p=x5_best_negative_p,
        x5_best_positive_r=x5_best_positive_r,
        x5_best_positive_p=x5_best_positive_p,
        x2_by_digit=x2_by_digit,
        x4_by_offset=x4_by_offset,
        x5_by_digit=x5_by_digit,
    )


def score_digits(target_row: HallRow, signal_summary: SignalSummary) -> tuple[list[int], dict[int, float]]:
    scores = {digit: 0.0 for digit in range(10)}

    if (
        signal_summary.x2_best_digit is not None
        and signal_summary.x2_best_r > 0
        and is_significant(signal_summary.x2_best_r, signal_summary.x2_best_p)
    ):
        scores[signal_summary.x2_best_digit] += 1

    rotated_digit: int | None = None
    if target_row.prev_first_digit is not None:
        rotated_digit = (target_row.prev_first_digit + signal_summary.x4_best_offset) % 10

    if rotated_digit is not None and is_significant(signal_summary.x3_r, signal_summary.x3_p):
        scores[rotated_digit] += 1

    if rotated_digit is not None and is_significant(signal_summary.x4_best_r, signal_summary.x4_best_p):
        scores[rotated_digit] += 1

    if (
        signal_summary.x5_best_negative_r < 0
        and is_significant(signal_summary.x5_best_negative_r, signal_summary.x5_best_negative_p)
    ):
        for digit, frequency in target_row.recent_freq.items():
            scores[digit] += (4 - frequency) * 0.5

    if (
        signal_summary.x5_best_positive_r > 0
        and is_significant(signal_summary.x5_best_positive_r, signal_summary.x5_best_positive_p)
    ):
        for digit, frequency in target_row.recent_freq.items():
            scores[digit] += frequency * 0.5

    for digit, frequency in target_row.recent_freq.items():
        scores[digit] += (4 - frequency) * 0.01

    ranking = sorted(range(10), key=lambda digit: (scores[digit], digit), reverse=True)
    return ranking, scores


def walk_forward_predict(rows: list[HallRow], min_train_size: int = 10) -> list[PredictionResult]:
    predictions: list[PredictionResult] = []
    for index in range(min_train_size, len(rows)):
        train_rows = rows[:index]
        target_row = rows[index]
        signal_summary = compute_signal_summary(train_rows)
        ranking, scores = score_digits(target_row, signal_summary)
        top3_pred = ranking[:3]

        reciprocal_rank = 0.0
        for rank, digit in enumerate(top3_pred, start=1):
            if digit in target_row.digits_list:
                reciprocal_rank = 1.0 / rank
                break

        predictions.append(
            PredictionResult(
                hall=target_row.hall,
                date=target_row.date,
                actual_digits=target_row.digits_list,
                top3_pred=top3_pred,
                hit=reciprocal_rank > 0,
                reciprocal_rank=reciprocal_rank,
                score_map=scores,
                active_signals=describe_active_signals(signal_summary, target_row),
            )
        )
    return predictions


def describe_active_signals(signal_summary: SignalSummary, target_row: HallRow) -> list[str]:
    names: list[str] = []
    if (
        signal_summary.x2_best_digit is not None
        and signal_summary.x2_best_r > 0
        and is_significant(signal_summary.x2_best_r, signal_summary.x2_best_p)
    ):
        names.append(f"X2({signal_summary.x2_best_digit})")
    if target_row.prev_first_digit is not None and is_significant(signal_summary.x3_r, signal_summary.x3_p):
        names.append("X3")
    if target_row.prev_first_digit is not None and is_significant(signal_summary.x4_best_r, signal_summary.x4_best_p):
        names.append(f"X4(offset={signal_summary.x4_best_offset})")
    if (
        signal_summary.x5_best_negative_r < 0
        and is_significant(signal_summary.x5_best_negative_r, signal_summary.x5_best_negative_p)
    ):
        names.append("X5-inv")
    if (
        signal_summary.x5_best_positive_r > 0
        and is_significant(signal_summary.x5_best_positive_r, signal_summary.x5_best_positive_p)
    ):
        names.append("X5-mom")
    return names


def compute_random_baseline(actual_digit_lists: list[list[int]]) -> tuple[float, float]:
    if not actual_digit_lists:
        return 0.0, 0.0

    hit3_total = 0.0
    mrr_total = 0.0
    denominator = math.comb(10, 3)

    for actual_digits in actual_digit_lists:
        k_value = len(set(actual_digits))
        if k_value <= 0:
            continue

        miss_combinations = math.comb(10 - k_value, 3) if 10 - k_value >= 3 else 0
        hit3_total += 1.0 - (miss_combinations / denominator)

        remaining_wrong = 10 - k_value
        probability_prefix = 1.0
        sample_space = 10
        expected_rr = 0.0
        for rank in range(1, 4):
            probability_hit_here = probability_prefix * (k_value / sample_space)
            expected_rr += probability_hit_here / rank
            probability_prefix *= remaining_wrong / sample_space
            remaining_wrong -= 1
            sample_space -= 1
        mrr_total += expected_rr

    total = len(actual_digit_lists)
    return hit3_total / total, mrr_total / total


def evaluate_predictions(predictions: list[PredictionResult]) -> dict[str, float]:
    if not predictions:
        return {
            "count": 0,
            "hit3": 0.0,
            "mrr": 0.0,
            "baseline_hit3": 0.0,
            "baseline_mrr": 0.0,
        }

    hit3 = sum(1.0 for prediction in predictions if prediction.hit) / len(predictions)
    mrr = sum(prediction.reciprocal_rank for prediction in predictions) / len(predictions)
    baseline_hit3, baseline_mrr = compute_random_baseline(
        [prediction.actual_digits for prediction in predictions]
    )
    return {
        "count": float(len(predictions)),
        "hit3": hit3,
        "mrr": mrr,
        "baseline_hit3": baseline_hit3,
        "baseline_mrr": baseline_mrr,
    }


def summarize_full_period_signals(rows: list[HallRow]) -> str:
    signal_summary = compute_signal_summary(rows)
    parts: list[str] = []

    significant_x2 = [
        digit
        for digit, (r_value, p_value) in signal_summary.x2_by_digit.items()
        if r_value > 0 and is_significant(r_value, p_value)
    ]
    if significant_x2:
        digits = ",".join(str(digit) for digit in sorted(significant_x2))
        parts.append(f"X2(digit{digits})")

    if is_significant(signal_summary.x3_r, signal_summary.x3_p):
        parts.append("X3")

    if is_significant(signal_summary.x4_best_r, signal_summary.x4_best_p):
        parts.append(f"X4(offset={signal_summary.x4_best_offset})")

    significant_x5 = [
        digit
        for digit, (r_value, p_value) in signal_summary.x5_by_digit.items()
        if r_value < 0 and is_significant(r_value, p_value)
    ]
    if significant_x5:
        parts.append("X5-inv")

    significant_x5_mom = [
        digit
        for digit, (r_value, p_value) in signal_summary.x5_by_digit.items()
        if r_value > 0 and is_significant(r_value, p_value)
    ]
    if significant_x5_mom:
        parts.append("X5-mom")

    return ", ".join(parts) if parts else "none"


def run_for_hall(db_path: Path, hall: str, min_train_size: int) -> None:
    rows = load_hall_rows(db_path, hall)
    predictions = walk_forward_predict(rows, min_train_size=min_train_size)
    metrics = evaluate_predictions(predictions)

    print(f"=== {hall} walk-forward 評価 ===")
    print(f"予測件数: {int(metrics['count'])}件")
    print(
        f"hit@3: {metrics['hit3'] * 100:.1f}%  "
        f"(baseline: {metrics['baseline_hit3'] * 100:.1f}%)"
    )
    print(
        f"MRR:   {metrics['mrr']:.2f}   "
        f"(baseline: {metrics['baseline_mrr']:.2f})"
    )
    print(f"有効シグナル（全期間通算）: {summarize_full_period_signals(rows)}")
    print("=== 日付別詳細 ===")
    for prediction in predictions:
        hit_mark = "✓" if prediction.hit else "✗"
        print(
            f"{prediction.date}   {prediction.actual_digits!s:<8}   "
            f"{prediction.top3_pred!s:<11}   {hit_mark}"
        )
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Predict next Saturday narabi start digits from poco_analysis.db"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DB_PATH,
        help="Path to poco analysis SQLite DB",
    )
    parser.add_argument(
        "--halls",
        nargs="+",
        default=list(DEFAULT_HALLS),
        help="Hall codes to evaluate independently",
    )
    parser.add_argument(
        "--min-train-size",
        type=int,
        default=10,
        help="Initial number of rows reserved for training before walk-forward starts",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for hall in args.halls:
        run_for_hall(args.db_path, hall, min_train_size=args.min_train_size)


def _nan_safe_value(value: float, negative_inf: bool) -> float:
    if math.isnan(value):
        return float("-inf") if negative_inf else float("inf")
    return value


if __name__ == "__main__":
    main()
