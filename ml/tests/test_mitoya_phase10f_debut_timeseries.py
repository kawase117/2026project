from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    machine_specs = [
        (501, "マイジャグラーV-501", 8, 130, 14, 1, 1, True),
        (502, "マイジャグラーV-502", 12, 75, 12, 2, 1, False),
        (503, "ノーマルA-503", 5, 130, 11, 3, 1, True),
        (504, "ノーマルB-504", 10, 85, 10, 4, 1, False),
        (505, "ノーマルC-505", 15, 130, 9, 5, 1, True),
    ]

    dates = pd.date_range("2026-01-01", "2026-05-10", freq="D")
    for date_idx, date in enumerate(dates):
        date_str = date.strftime("%Y%m%d")
        dd = int(date_str[-2:])
        is_xdds_day = dd in {7, 14, 17, 24, 27}
        for machine_number, machine_name, start_offset, end_offset, base_diff, x, y, active in machine_specs:
            debut_days = date_idx - start_offset
            if date_idx > end_offset:
                continue
            if not active and debut_days > 30:
                continue
            current_name = machine_name if date_idx >= start_offset else f"旧機種-{machine_number}"
            if date_idx < start_offset:
                current_name = f"旧機種-{machine_number}"
            if machine_name.startswith("マイジャグラー"):
                segment_bonus = 20
            else:
                segment_bonus = 0
            debut_bonus = -25 if debut_days <= 30 else (15 if debut_days <= 60 else 70)
            survival_bonus = 35 if active else -10
            xdds_bonus = 45 if is_xdds_day else 0
            removal_drag = -15 if not active else 0
            diff = float(
                base_diff + debut_bonus + survival_bonus + xdds_bonus + removal_drag + date_idx * 0.4 + segment_bonus
            )
            rows.append(
                {
                    "date": date_str,
                    "machine_number": machine_number,
                    "machine_name": current_name,
                    "diff": diff,
                    "games": 1500,
                    "section": "501-522",
                    "x": x,
                    "y": y,
                    "rank_from_aisle": x,
                    "dd": dd,
                }
            )
    return pd.DataFrame(rows)


def test_step1_cohort_has_all_bins() -> None:
    import eda.mitoya_phase10f_debut_timeseries as phase10f

    artifacts = phase10f.build_all_artifacts(_make_frame())

    step1 = artifacts["step1_cohort_tracking"]
    assert list(step1.columns) == ["segment", "debut_bin", "n", "avg_diff", "plus_rate", "n_machines"]
    assert set(step1["segment"].astype(str)) == {"h_jug", "h_nonjug"}
    assert set(step1["debut_bin"].astype(str)) == {"0-30", "31-60", "61-90", "91-120", "121+"}


def test_step2_survival_groups() -> None:
    import eda.mitoya_phase10f_debut_timeseries as phase10f

    artifacts = phase10f.build_all_artifacts(_make_frame())

    step2 = artifacts["step2_survival_bias"]
    assert list(step2.columns) == ["segment", "group", "debut_avg_diff", "debut_n", "max_days_median", "n_machines"]
    assert set(step2["group"].astype(str)) == {"survived", "removed"}


def test_step2_mwu_result() -> None:
    import eda.mitoya_phase10f_debut_timeseries as phase10f

    artifacts = phase10f.build_all_artifacts(_make_frame())

    step2 = artifacts["step2_survival_mwu"]
    assert list(step2.columns) == ["segment", "u_stat", "p_value", "survived_debut_avg", "removed_debut_avg", "diff"]
    assert set(step2["segment"].astype(str)) == {"h_jug", "h_nonjug"}
    assert step2["p_value"].notna().all()


def test_step3_scope_values() -> None:
    import eda.mitoya_phase10f_debut_timeseries as phase10f

    artifacts = phase10f.build_all_artifacts(_make_frame())

    step3 = artifacts["step3_xdds_debut_premium"]
    assert list(step3.columns) == ["segment", "scope", "debut_bin", "n", "avg_diff", "plus_rate"]
    assert set(step3["scope"].astype(str)) == {"X_DDS", "非イベント日"}


def test_step4_ranking_threshold() -> None:
    import eda.mitoya_phase10f_debut_timeseries as phase10f

    artifacts = phase10f.build_all_artifacts(_make_frame())

    step4 = artifacts["step4_machine_ranking"]
    assert list(step4.columns) == [
        "machine_name",
        "debut_avg_diff",
        "debut_n",
        "mature_avg_diff",
        "mature_n",
        "improvement",
        "rank",
    ]
    assert (step4["debut_n"] >= 30).all()
    assert (step4["mature_n"] >= 30).all()
    assert step4["rank"].tolist() == list(range(1, len(step4) + 1))


def test_generate_report_creates_files(tmp_path: Path, monkeypatch) -> None:
    import eda.mitoya_phase10f_debut_timeseries as phase10f

    monkeypatch.setattr(phase10f, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase10f.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "step1_cohort_tracking.csv",
        "step2_survival_bias.csv",
        "step2_survival_mwu.csv",
        "step3_xdds_debut_premium.csv",
        "step4_machine_ranking.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
