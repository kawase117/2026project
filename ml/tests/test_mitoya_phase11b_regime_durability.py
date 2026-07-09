from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _bucket_rank(machine_number: int) -> int:
    if 641 <= machine_number <= 645 or 501 <= machine_number <= 505:
        return 1
    if 646 <= machine_number <= 650 or 506 <= machine_number <= 510:
        return 3
    if 651 <= machine_number <= 655 or 511 <= machine_number <= 515:
        return 6
    return 11


def _corner_bonus(rank: int) -> float:
    if rank <= 1:
        return 80.0
    if rank <= 4:
        return 50.0
    if rank <= 9:
        return 20.0
    return -10.0


def _jug_name(machine_number: int, date: pd.Timestamp) -> str:
    if machine_number <= 650 and date >= pd.Timestamp("2025-02-01"):
        return "ファンキージャグラー2"
    return "マイジャグラーV"


def _nonjug_name(machine_number: int, date: pd.Timestamp) -> str:
    if machine_number in {501, 502, 503, 504} and date >= pd.Timestamp("2025-01-10"):
        return "海物語5R"
    if machine_number in {505, 506, 507, 508} and date >= pd.Timestamp("2025-02-15"):
        return "海物語5DX"
    return "海物語5"


def _nonjug_phase_bonus(machine_number: int, date: pd.Timestamp) -> float:
    if machine_number in {501, 502, 503, 504}:
        if date < pd.Timestamp("2025-01-10"):
            return 10.0
        days = (date - pd.Timestamp("2025-01-10")).days
        if days == 0:
            return 40.0
        if days <= 30:
            return 30.0
        return 20.0
    if machine_number in {505, 506, 507, 508}:
        if date < pd.Timestamp("2025-02-15"):
            return 10.0
        days = (date - pd.Timestamp("2025-02-15")).days
        if days == 0:
            return 40.0
        if days <= 30:
            return 30.0
        return 20.0
    return 10.0


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2025-01-01", "2025-04-01", freq="D")

    for date in dates:
        day_index = (date - dates[0]).days
        for offset, machine_number in enumerate(range(641, 661), start=1):
            rank = _bucket_rank(machine_number)
            machine_name = _jug_name(machine_number, date)
            diff = (
                _corner_bonus(rank)
                + (5.0 if machine_name != "マイジャグラーV" else 0.0)
                + day_index * 0.1
                + (offset % 3)
            )
            rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "section": "641-657",
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "diff": diff,
                    "games": 1500 + day_index,
                    "x": offset,
                    "y": 1,
                    "rank_from_aisle": rank,
                }
            )

        for offset, machine_number in enumerate(range(501, 521), start=1):
            rank = _bucket_rank(machine_number)
            machine_name = _nonjug_name(machine_number, date)
            diff = (
                _nonjug_phase_bonus(machine_number, date) + _corner_bonus(rank) * 0.1 + day_index * 0.05 + (offset % 2)
            )
            rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "section": "501-522",
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "diff": diff,
                    "games": 1500 + day_index,
                    "x": offset,
                    "y": 1,
                    "rank_from_aisle": rank,
                }
            )

    return pd.DataFrame(rows)


@pytest.fixture()
def dummy_frame() -> pd.DataFrame:
    return _make_frame()


def test_detect_regime_boundary(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11b_regime_durability as phase11b
    from eda.mitoya_prompt_common import add_debut_phase, add_event_category

    work = add_event_category(add_debut_phase(dummy_frame))
    boundary = phase11b.detect_regime_boundary(work)

    assert isinstance(boundary, pd.Timestamp)
    assert boundary.strftime("%Y%m%d") == "20250201"


def test_step2_corner_both_regimes(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11b_regime_durability as phase11b

    artifacts = phase11b.build_all_artifacts(dummy_frame)
    step2 = artifacts["step2_corner_regime_stats"]

    assert set(step2["segment"].astype(str)) == {"h_jug", "h_nonjug"}
    assert set(step2["regime"].astype(str)) == {"pre", "post"}
    assert {"corner1", "corner2-4", "corner5-9", "corner10+"} <= set(step2["corner_bucket"].astype(str))


def test_step3_corner_rank_rho(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11b_regime_durability as phase11b

    artifacts = phase11b.build_all_artifacts(dummy_frame)
    step3 = artifacts["step3_corner_rank_correlation"]

    assert set(step3["segment"].astype(str)) == {"h_jug", "h_nonjug"}
    assert step3["spearman_rho"].dropna().ge(0.9).all()


def test_step4_debut_both_regimes(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11b_regime_durability as phase11b

    artifacts = phase11b.build_all_artifacts(dummy_frame)
    step4 = artifacts["step4_debut_regime_stats"]

    assert "h_nonjug" in set(step4["segment"].astype(str))
    nonjug = step4.loc[step4["segment"].astype(str).eq("h_nonjug")]
    assert set(nonjug["regime"].astype(str)) == {"pre", "post"}
    assert {"pre_existing", "debut", "growth"} <= set(nonjug["debut_phase"].astype(str))


def test_step5_debut_rank_rho(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11b_regime_durability as phase11b

    artifacts = phase11b.build_all_artifacts(dummy_frame)
    step5 = artifacts["step5_debut_rank_correlation"]

    assert set(step5["segment"].astype(str)) == {"h_nonjug"}
    row = step5.iloc[0]
    assert row["pre_best_phase"] == "debut"
    assert row["post_best_phase"] == "debut"
    assert row["spearman_rho"] >= 0.9


def test_step6_verdict_values(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11b_regime_durability as phase11b

    artifacts = phase11b.build_all_artifacts(dummy_frame)
    step6 = artifacts["step6_stability_summary"]

    assert set(step6["verdict"].astype(str)) <= {"✅安定", "⚠️不安定", "✗効果なし", "❌崩壊"}
    assert "✅安定" in set(step6["verdict"].astype(str))


def test_generate_report_creates_files(
    dummy_frame: pd.DataFrame, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eda import mitoya_phase11b_regime_durability as phase11b

    monkeypatch.setattr(phase11b, "load_mitoya_frame", lambda join_layout=True: dummy_frame)

    exit_code = phase11b.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    expected = [
        "step1_regime_boundary.csv",
        "step2_corner_regime_stats.csv",
        "step2_corner_regime_kw.csv",
        "step3_corner_rank_correlation.csv",
        "step4_debut_regime_stats.csv",
        "step4_debut_regime_kw.csv",
        "step5_debut_rank_correlation.csv",
        "step6_stability_summary.csv",
        "report.md",
    ]
    for name in expected:
        assert (tmp_path / name).exists()
