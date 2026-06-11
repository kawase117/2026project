from __future__ import annotations

import pandas as pd

from ml.last_digit.tail_ltr_mitoya_nextday import (
    annotate_ranking_rows,
    build_parser,
    resolve_target_bucket_context,
    summarize_seed_agreement,
)


def test_parser_exposes_mitoya_nextday_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([])

    assert args.db_glob == "みとや大森町店.db"
    assert args.output_prefix == "db/experiments/mitoya_nextday"
    assert args.sunday_q_override == 0.65
    assert args.a_weight == 1.0
    assert args.non_a_weight == 1.0


def test_resolve_target_bucket_context_classifies_specific_dd() -> None:
    parser = build_parser()
    args = parser.parse_args(["--q-grid-nonwed", "0.1,0.3,0.5"])

    xday_ctx = resolve_target_bucket_context(args, pd.Timestamp("2026-06-14"))
    other_ctx = resolve_target_bucket_context(args, pd.Timestamp("2026-06-11"))

    assert xday_ctx["day_bucket"] == "x_day"
    assert xday_ctx["decision"] == "adopt"
    assert xday_ctx["specific_dd"] == 4
    assert xday_ctx["active_q"] == [0.1, 0.3, 0.5]
    assert xday_ctx["sunday_q_override_applied"] is False

    assert other_ctx["day_bucket"] == "others"
    assert other_ctx["decision"] == "exclude"
    assert other_ctx["specific_dd"] is None
    assert other_ctx["active_q"] == [0.1, 0.3, 0.5]
    assert other_ctx["sunday_q_override_applied"] is False


def test_annotate_ranking_rows_adds_bucket_and_decision() -> None:
    rows = [{"rank": 1, "last_digit": "7", "combined_score": 1.2}]

    out = annotate_ranking_rows(
        rows,
        day_bucket="x_day",
        decision="adopt",
        specific_dd=4,
    )

    assert out[0]["day_bucket"] == "x_day"
    assert out[0]["decision"] == "adopt"
    assert out[0]["specific_dd"] == 4


def test_parser_exposes_compare_mode_seed_list() -> None:
    parser = build_parser()
    args = parser.parse_args(["--compare-mode", "--compare-seeds", "42,77,303"])

    assert args.compare_mode is True
    assert args.compare_seeds == "42,77,303"


def test_summarize_seed_agreement_marks_xday_consensus_high_confidence() -> None:
    rows = [
        {"seed": 42, "combined_top1_digit": "5"},
        {"seed": 77, "combined_top1_digit": "5"},
        {"seed": 303, "combined_top1_digit": "5"},
    ]

    summary = summarize_seed_agreement(rows, target_ctx={"day_bucket": "x_day"})

    assert summary["consensus_top1_digit"] == "5"
    assert summary["consensus_top1_count"] == 3
    assert summary["consensus_top1_ratio"] == 1.0
    assert summary["all_same_top1"] is True
    assert summary["is_high_confidence"] is True


def test_summarize_seed_agreement_requires_xday_for_high_confidence() -> None:
    rows = [
        {"seed": 42, "combined_top1_digit": "5"},
        {"seed": 77, "combined_top1_digit": "5"},
        {"seed": 303, "combined_top1_digit": "5"},
    ]

    summary = summarize_seed_agreement(rows, target_ctx={"day_bucket": "others"})

    assert summary["all_same_top1"] is True
    assert summary["is_high_confidence"] is False
