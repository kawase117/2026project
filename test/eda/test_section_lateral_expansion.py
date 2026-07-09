from __future__ import annotations

from pathlib import Path

import pandas as pd

from eda.section_lateral_expansion import HALL_CONFIGS, HallArtifacts, _load_coords, build_outputs


def _make_artifact() -> HallArtifacts:
    coords = pd.DataFrame(
        {
            "machine_number": [1, 2],
            "floor": ["2F", "2F"],
            "section": ["A", "B"],
            "section_min": [1, 2],
            "section_max": [1, 2],
            "section_size": [1, 1],
            "X": [10, 20],
            "Y": [1, 1],
            "display_y": [1, 1],
            "rank_from_min": [1, 2],
            "rank_from_max": [1, 2],
            "lr": ["L", "R"],
            "kakuban": [1, 2],
        }
    )
    section_eval = pd.DataFrame(
        {
            "hall": ["蒲田1"],
            "test_date": ["2026-01-01"],
            "section": ["A"],
            "floor": ["2F"],
            "section_size": [1],
            "section_score": [0.5],
            "section_hit_rate": [0.4],
            "section_rank": [1],
            "section_delta_pp": [-10.0],
        }
    )
    summary = pd.DataFrame(
        {
            "hall": ["蒲田1"] * 4,
            "top_k": [1, 3, 5, 10],
            "eval_days": [1, 1, 1, 1],
            "section_rho": [0.1, 0.1, 0.1, 0.1],
            "section_p": [0.2, 0.2, 0.2, 0.2],
            "section_baseline_rate": [0.4, 0.4, 0.4, 0.4],
            "section_top_rate": [0.5, 0.5, 0.5, 0.5],
            "section_lift": [1.25, 1.25, 1.25, 1.25],
            "machine_baseline_rate": [0.3, 0.3, 0.3, 0.3],
            "selected_machine_rate": [0.35, 0.35, 0.35, 0.35],
            "selected_machine_lift": [1.166667, 1.166667, 1.166667, 1.166667],
            "n_machines_per_day": [2, 2, 2, 2],
            "global_hist_rate": [0.33, 0.33, 0.33, 0.33],
            "global_hist_lift": [1.1, 1.1, 1.1, 1.1],
        }
    )
    mini_audit = pd.DataFrame(
        columns=[
            "hall",
            "section",
            "floor",
            "section_min",
            "section_max",
            "section_size",
            "section_score_mean",
            "section_score_std",
            "n_eval_days",
        ]
    )
    return HallArtifacts(
        hall="kamata1",
        label="蒲田1",
        frame=pd.DataFrame(
            {
                "seg": ["A", "N"],
                "floor": ["2F", "2F"],
                "section": ["A", "B"],
                "date_dt": pd.to_datetime(["2026-01-01", "2026-01-01"]),
            }
        ),
        coords=coords,
        section_eval=section_eval,
        summary=summary,
        mini_audit=mini_audit,
        top5_changes=0,
        top3_changes=0,
    )


def test_mitoya_config_and_coords_loader_accepts_missing_display_x(tmp_path: Path) -> None:
    assert "mitoya" in HALL_CONFIGS
    assert HALL_CONFIGS["mitoya"].label == "みとや大森町店"

    coords_path = tmp_path / "mitoya_coords.csv"
    pd.DataFrame(
        {
            "floor": ["2F"],
            "machine_number": [101],
            "X": [10],
            "Y": [20],
            "display_y": [30],
            "section": ["S1"],
            "section_min": [1],
            "section_max": [3],
            "rank_from_min": [1],
            "rank_from_max": [3],
        }
    ).to_csv(coords_path, index=False)

    coords = _load_coords([coords_path])

    assert coords.loc[0, "machine_number"] == 101
    assert coords.loc[0, "display_y"] == 30
    assert coords.loc[0, "section_size"] == 1


def test_build_outputs_writes_kamata1_sensitivity_artifacts(tmp_path: Path, monkeypatch) -> None:
    artifact = _make_artifact()

    def fake_evaluate_hall(hall: str, **_kwargs):
        assert hall == "kamata1"
        return artifact

    monkeypatch.setattr("eda.section_lateral_expansion._evaluate_hall", fake_evaluate_hall)

    section_eval, hall_summary, mini_audit, report = build_outputs(
        halls=("kamata1",),
        output_dir=tmp_path,
        min_games=1000,
        window_days=90,
        eval_days=60,
        top_ks=(1, 3, 5, 10),
        top_machines_per_section=5,
    )

    assert not section_eval.empty
    assert not hall_summary.empty
    assert mini_audit.empty
    assert "## 8. 蒲田1 感度分析" in report
    assert (tmp_path / "kamata1_min_games_sensitivity.csv").exists()
    assert (tmp_path / "kamata1_event_only.csv").exists()
