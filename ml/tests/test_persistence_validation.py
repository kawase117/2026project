from __future__ import annotations

from pathlib import Path

import pandas as pd


def test_parser_exposes_expected_defaults() -> None:
    from ml.experiments.label_redesign import persistence_validation as analysis

    parser = analysis.build_parser()
    args = parser.parse_args([])

    assert args.halls == ["\u84b2\u75307", "\u84b2\u75301", "\u307f\u3068\u3084"]
    assert args.input_dir == Path("ml/experiments/label_redesign/results")
    assert args.output_dir == Path("ml/experiments/label_redesign/results")
    assert args.min_cell_pairs == 30
    assert args.n_bootstrap == 1000
    assert args.random_seed == 42


def _make_raw_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    machine_rows = [
        ("20260701", 101, 0, 0.1, 80.0),
        ("20260702", 101, 1, 0.9, 120.0),
        ("20260704", 101, 0, 0.2, 80.0),
        ("20260701", 202, 1, 0.8, 120.0),
        ("20260702", 202, 0, 0.2, 80.0),
    ]
    for date, machine_number, hit104, p_high_setting, payout_rate in machine_rows:
        rows.append(
            {
                "date": date,
                "machine_name": "machine-a" if machine_number == 101 else "machine-b",
                "machine_number": machine_number,
                "games": 500,
                "hit104": hit104,
                "p_high_setting": p_high_setting,
                "payout_rate": payout_rate,
            }
        )
    return pd.DataFrame(rows)


def _make_pair_frame(n_pairs: int, *, hall: str = "\u84b2\u75307") -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx in range(n_pairs):
        current_date = pd.Timestamp("2026-07-01") + pd.Timedelta(days=idx)
        next_date = current_date + pd.Timedelta(days=1)
        hit104 = 1 if idx % 2 == 1 else 0
        p_high_setting = 0.9 if idx % 2 == 0 else 0.1
        next_hit104 = 1 if p_high_setting > 0.5 else 0
        next_payout_rate = 120.0 if next_hit104 else 80.0
        rows.append(
            {
                "hall": hall,
                "date": current_date,
                "next_date": next_date,
                "machine_name": f"machine-{idx % 3}",
                "machine_number": 1000 + idx % 3,
                "dd": current_date.day,
                "machine_digit": (1000 + idx % 3) % 10,
                "hit104": hit104,
                "p_high_setting": p_high_setting,
                "payout_rate": 80.0 if hit104 == 0 else 120.0,
                "next_hit104": next_hit104,
                "next_payout_rate": next_payout_rate,
            }
        )
    return pd.DataFrame(rows)


def test_build_next_day_pairs_skips_non_consecutive_dates() -> None:
    from ml.experiments.label_redesign import persistence_validation as analysis

    pairs = analysis._build_next_day_pairs(_make_raw_frame(), hall="\u84b2\u75307")

    assert len(pairs) == 2
    assert pairs["next_date"].dt.strftime("%Y%m%d").tolist() == ["20260702", "20260702"]
    assert pairs["machine_number"].tolist() == [101, 202]


def test_hall_summary_prefers_p_high_setting_when_it_tracks_next_hit104() -> None:
    from ml.experiments.label_redesign import persistence_validation as analysis

    pairs = _make_pair_frame(40)
    summary = analysis._summarize_hall(pairs, hall="\u84b2\u75307", n_bootstrap=256, random_seed=7)

    row = summary.iloc[0]
    assert row["n_next_day_pairs"] == 40
    assert row["auc_p_high_setting_predicts_next_hit104"] == 1.0
    assert row["auc_diff"] > 0.9
    assert bool(row["auc_diff_significant(bool)"]) is True
    assert row["auc_diff_ci_lo"] > 0


def test_random_noise_scores_hover_near_chance() -> None:
    from ml.experiments.label_redesign import persistence_validation as analysis

    rng = pd.Series(range(400))
    noise = pd.Series(range(400), dtype=float).sample(frac=1.0, random_state=11).to_numpy() / 400.0
    frame = pd.DataFrame(
        {
            "hall": "\u84b2\u75307",
            "date": pd.to_datetime("2026-07-01") + pd.to_timedelta(rng, unit="D"),
            "next_date": pd.to_datetime("2026-07-02") + pd.to_timedelta(rng, unit="D"),
            "machine_name": [f"machine-{i}" for i in range(400)],
            "machine_number": [1000 + (i % 5) for i in range(400)],
            "dd": [((pd.Timestamp("2026-07-01") + pd.Timedelta(days=int(i))).day) for i in rng],
            "machine_digit": [(1000 + (i % 5)) % 10 for i in range(400)],
            "hit104": [i % 2 for i in rng],
            "p_high_setting": noise,
            "payout_rate": [120.0 if i % 2 else 80.0 for i in rng],
            "next_hit104": [i % 2 for i in rng],
            "next_payout_rate": [120.0 if i % 2 else 80.0 for i in rng],
        }
    )

    summary = analysis._summarize_hall(frame, hall="\u84b2\u75307", n_bootstrap=128, random_seed=3)

    row = summary.iloc[0]
    assert abs(float(row["auc_p_high_setting_predicts_next_hit104"]) - 0.5) < 0.1


def test_null_difference_data_stays_not_significant() -> None:
    from ml.experiments.label_redesign import persistence_validation as analysis

    rng = pd.Series(range(200))
    shared_score = pd.Series(range(200), dtype=float).sample(frac=1.0, random_state=21).to_numpy() / 200.0
    frame = pd.DataFrame(
        {
            "hall": "\u84b2\u75307",
            "date": pd.to_datetime("2026-07-01") + pd.to_timedelta(rng, unit="D"),
            "next_date": pd.to_datetime("2026-07-02") + pd.to_timedelta(rng, unit="D"),
            "machine_name": [f"machine-{i}" for i in range(200)],
            "machine_number": [3000 + (i % 5) for i in range(200)],
            "dd": [((pd.Timestamp("2026-07-01") + pd.Timedelta(days=int(i))).day) for i in rng],
            "machine_digit": [(3000 + (i % 5)) % 10 for i in range(200)],
            "hit104": [i % 2 for i in rng],
            "p_high_setting": shared_score,
            "payout_rate": [120.0 if i % 2 else 80.0 for i in rng],
            "next_hit104": [i % 2 for i in rng],
            "next_payout_rate": [120.0 if i % 2 else 80.0 for i in rng],
        }
    )
    frame["hit104"] = frame["p_high_setting"]

    summary = analysis._summarize_hall(frame, hall="\u84b2\u75307", n_bootstrap=128, random_seed=9)

    row = summary.iloc[0]
    assert abs(float(row["auc_diff"])) < 1e-12
    assert bool(row["auc_diff_significant(bool)"]) is False


def test_negative_auc_diff_can_still_be_significant() -> None:
    from ml.experiments.label_redesign import persistence_validation as analysis

    rows: list[dict[str, object]] = []
    for idx in range(80):
        current_date = pd.Timestamp("2026-07-01") + pd.Timedelta(days=idx)
        next_date = current_date + pd.Timedelta(days=1)
        next_hit104 = 1 if idx % 2 == 0 else 0
        rows.append(
            {
                "hall": "\u84b2\u75307",
                "date": current_date,
                "next_date": next_date,
                "machine_name": f"machine-{idx % 4}",
                "machine_number": 2000 + idx % 4,
                "dd": current_date.day,
                "machine_digit": (2000 + idx % 4) % 10,
                "hit104": next_hit104,
                "p_high_setting": 1.0 - next_hit104,
                "payout_rate": 120.0 if next_hit104 else 80.0,
                "next_hit104": next_hit104,
                "next_payout_rate": 120.0 if next_hit104 else 80.0,
            }
        )
    frame = pd.DataFrame(rows)

    summary = analysis._summarize_hall(frame, hall="\u84b2\u75307", n_bootstrap=128, random_seed=5)

    row = summary.iloc[0]
    assert row["auc_diff"] < 0
    assert bool(row["auc_diff_significant(bool)"]) is True


def test_by_cell_excludes_low_sample_cells() -> None:
    from ml.experiments.label_redesign import persistence_validation as analysis

    pairs = _make_pair_frame(29)
    by_cell = analysis._summarize_by_cell(pairs, hall="\u84b2\u75307", min_cell_pairs=30)

    assert len(by_cell) == 29
    assert by_cell["note"].str.contains("excluded: n_pairs < 30").all()
    assert by_cell["auc_hit104"].isna().all()
    assert by_cell["auc_p_high_setting"].isna().all()


def test_main_writes_expected_outputs(tmp_path: Path) -> None:
    from ml.experiments.label_redesign import persistence_validation as analysis

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    raw = _make_raw_frame()
    raw.to_csv(input_dir / "\u84b2\u75307_soft_label_comparison.csv", index=False, encoding="utf-8-sig")

    exit_code = analysis.main(
        [
            "--halls",
            "\u84b2\u75307",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--n-bootstrap",
            "64",
        ]
    )

    assert exit_code == 0
    summary_path = output_dir / "\u84b2\u75307_persistence_validation.csv"
    by_cell_path = output_dir / "\u84b2\u75307_persistence_validation_by_cell.csv"
    assert summary_path.exists()
    assert by_cell_path.exists()

    summary = pd.read_csv(summary_path, encoding="utf-8-sig")
    assert list(summary.columns) == [
        "hall",
        "n_next_day_pairs",
        "corr_hit104_vs_next_payout",
        "corr_p_high_setting_vs_next_payout",
        "auc_hit104_predicts_next_hit104",
        "auc_p_high_setting_predicts_next_hit104",
        "auc_diff",
        "auc_diff_ci_lo",
        "auc_diff_ci_hi",
        "auc_diff_significant(bool)",
    ]
