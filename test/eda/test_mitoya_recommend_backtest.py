from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from eda import mitoya_recommend as recommend
from eda import mitoya_recommend_backtest as backtest
from eda import mitoya_recommend_optimize as optimize


def _make_frame() -> pd.DataFrame:
    dates = [
        "20250701",
        "20250702",
        "20250703",
        "20250704",
        "20250707",
        "20250708",
        "20250709",
        "20250710",
        "20250711",
        "20250712",
    ]
    rows: list[dict[str, object]] = []
    machine_specs = [
        (1001, "HJ-1", "641-657", 1, "h_jug"),
        (1002, "HJ-2", "658-674", 2, "h_jug"),
        (1003, "HJ-3", "675-691", 5, "h_jug"),
        (1004, "HJ-4", "641-657", 10, "h_jug"),
        (2001, "HN-1", "501-522", 1, "h_nonjug"),
        (2002, "HN-2", "523-539", 1, "h_nonjug"),
        (2003, "HN-3", "540-556", 3, "h_nonjug"),
        (2004, "HN-4", "557-573", 6, "h_nonjug"),
        (2005, "HN-5", "574-590", 10, "h_nonjug"),
        (2006, "HN-6", "591-607", 4, "h_nonjug"),
        (3001, "VJ-1", "712-722", 1, "v_jug"),
        (3002, "VJ-2", "723-733", 2, "v_jug"),
        (3003, "VJ-3", "734-744", 5, "v_jug"),
        (3004, "VJ-4", "723-733", 10, "v_jug"),
        (4001, "VN-1", "692-700", 1, "v_nonjug"),
        (4002, "VN-2", "701-711", 2, "v_nonjug"),
        (4003, "VN-3", "745-755", 5, "v_nonjug"),
        (4004, "VN-4", "701-711", 10, "v_nonjug"),
        (5001, "M-1", "805-815", 1, "mixed_805"),
        (5002, "M-2", "805-815", 4, "mixed_805"),
    ]

    for day_index, date in enumerate(dates):
        dd = int(date[-2:])
        is_xdds = dd in recommend.X_DDS
        for machine_number, machine_name, section, rank_from_aisle, segment in machine_specs:
            corner_bucket = backtest.corner_bucket_from_rank(rank_from_aisle)
            diff = {
                "h_jug": 120 + (20 if corner_bucket == "corner1" else 0) + (10 if section == "675-691" else 0),
                "h_nonjug": 40
                + (90 if is_xdds and corner_bucket == "corner1" else 0)
                + (-30 if not is_xdds and corner_bucket == "corner1" else 0),
                "v_jug": 15 + (8 if is_xdds else 0),
                "v_nonjug": -20,
                "mixed_805": 50 + (60 if is_xdds and machine_number == 5001 else 0),
            }[segment]
            rows.append(
                {
                    "date": date,
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "section": section,
                    "rank_from_aisle": rank_from_aisle,
                    "games": 1200 + day_index * 10,
                    "diff": diff + day_index,
                    "dd": dd,
                }
            )
    return pd.DataFrame(rows)


def test_run_backtest_writes_outputs_and_excludes_v_nonjug(tmp_path: Path) -> None:
    frame = _make_frame()

    result = backtest.run_backtest(frame=frame, output_dir=tmp_path, top_n=10, random_samples=20)

    daily_path = tmp_path / "mitoya_backtest_daily.csv"
    summary_path = tmp_path / "mitoya_backtest_summary.csv"
    report_path = tmp_path / "mitoya_backtest_report.md"

    assert daily_path.exists()
    assert summary_path.exists()
    assert report_path.exists()

    daily = pd.read_csv(daily_path)
    summary = pd.read_csv(summary_path)

    expected_daily_cols = {
        "test_date",
        "dd",
        "is_xdds",
        "window",
        "avg_diff_top10",
        "avg_diff_random",
        "lift",
        "hit@3",
        "hit@5",
        "hit@10",
        "win_rate",
        "n_machines",
    }
    assert expected_daily_cols.issubset(set(daily.columns))
    assert daily["lift"].notna().any()

    assert set(summary["event_type"]) == {"all", "xdds", "non_xdds"}
    assert set(summary["window"]) == {"pre", "post"}

    details = result["details"]
    assert not details.empty
    assert "v_nonjug" not in set(details["segment"])


def test_optimize_outputs_grid_best_and_vectorized_score_matches_row_score(tmp_path: Path) -> None:
    frame = _make_frame()

    result = optimize.run_optimization(frame=frame, output_dir=tmp_path, top_n=10, random_samples=20)

    grid_path = tmp_path / "mitoya_optimize_grid.csv"
    best_path = tmp_path / "mitoya_optimize_best.json"
    report_path = tmp_path / "mitoya_optimize_report.md"

    assert grid_path.exists()
    assert best_path.exists()
    assert report_path.exists()

    grid = pd.read_csv(grid_path)
    assert {"stage", "param_name", "param_value", "lift@10_A", "lift@10_B", "lift@10_avg"}.issubset(grid.columns)
    best = json.loads(best_path.read_text(encoding="utf-8"))
    assert "stage1" in best

    prepared = optimize.prepare_optimization_frame(frame)
    section_baselines = optimize.build_section_baselines(prepared.loc[prepared["date"] < "20250707"])
    feature_frame = optimize.build_feature_frame(prepared, dd=4, section_baselines=section_baselines)
    row = feature_frame.iloc[0]
    weights = optimize.current_weight_vector()
    vector_score = optimize.score_features(feature_frame.iloc[[0]], weights).iloc[0]
    row_score = recommend._score_machine(row, 4, True, section_baselines)
    assert vector_score == row_score


def test_every_weight_key_has_a_feature_column() -> None:
    """CURRENT_WEIGHTS のキーは必ず特徴量列を持つ。

    score_features は feature_frame に無い重みキーを黙ってスキップするため、
    列名の typo や追加漏れがあっても例外にならず、加点だけが静かに消える。
    """
    frame = _make_frame()
    prepared = backtest.prepare_backtest_frame(frame)
    section_baselines = backtest.build_section_baselines(prepared)
    feature_frame = backtest.build_feature_frame(prepared, dd=4, section_baselines=section_baselines)

    expected = set(backtest.CURRENT_WEIGHTS) - {"section_baseline_scale"}
    missing = expected - set(feature_frame.columns)
    assert not missing, f"重みキーに対応する特徴量列が無い: {sorted(missing)}"


def test_optimizer_feature_keys_cover_all_weights() -> None:
    """optimizer の FEATURE_KEYS が CURRENT_WEIGHTS と一致する。

    ここが欠けると最適化の高速パスだけが新特徴を無視して探索する。
    実際 h_nonjug_corner24_xdds / h_nonjug_corner59_xdds が漏れていた（2026-07-24）。
    """
    expected = set(backtest.CURRENT_WEIGHTS) - {"section_baseline_scale"}
    assert set(optimize.FEATURE_KEYS) == expected
    assert "section_baseline_scale" not in optimize.FEATURE_KEYS


def test_scorer_parity_across_all_segments_and_buckets() -> None:
    """_score_machine（if分岐）と score_features（ベクトル内積）が全行で一致する。

    従来のテストは feature_frame.iloc[0]（h_jug/641-657/rank1）1行のみを比較しており、
    h_nonjug の corner2-4 / corner5-9、523-539 除外、corner10+ を検証できていなかった。
    """
    frame = _make_frame()
    prepared = backtest.prepare_backtest_frame(frame)
    section_baselines = backtest.build_section_baselines(prepared)
    weights = backtest.current_weight_vector()

    # v_nonjug は _score_machine のみ -9999 を返す仕様なので比較対象から外す
    target = prepared.loc[~prepared["segment"].isin(recommend.AVOID_SEGMENTS)]
    assert not target.empty

    # X_DDS日 / DD24特殊 / 非イベント日 を網羅する
    for dd in (4, 24, 15):
        feature_frame = backtest.build_feature_frame(target, dd=dd, section_baselines=section_baselines)
        vector_scores = backtest.score_features(feature_frame, weights).to_numpy()
        row_scores = feature_frame.apply(
            lambda r: recommend._score_machine(r, dd, dd in recommend.X_DDS, section_baselines),
            axis=1,
        ).to_numpy()
        mismatched = [
            (int(feature_frame.iloc[i]["machine_number"]), float(vector_scores[i]), float(row_scores[i]))
            for i in range(len(feature_frame))
            if abs(vector_scores[i] - row_scores[i]) > 1e-9
        ]
        assert not mismatched, f"dd={dd} でスコア不一致: {mismatched[:5]}"

    # カバレッジ自体の確認（フィクスチャが痩せたら気づけるように）
    buckets = set(backtest.build_feature_frame(target, dd=4, section_baselines=section_baselines)["corner_bucket"])
    assert {"corner1", "corner2-4", "corner5-9", "corner10+"} <= buckets
    assert "523-539" in set(target["section"])


def test_523_539_corner1_gets_no_premium() -> None:
    """523-539 の角1は X_DDS日でも角1プレミアムを受け取らない。

    全期間プールで 523-539角1=-27 は他セクション角1=+797 に劣り（MWU p=0.019）、
    セクション内でも角1と角2+に差がない（p=0.50）ため除外している。
    """
    frame = _make_frame()
    prepared = backtest.prepare_backtest_frame(frame)
    section_baselines = backtest.build_section_baselines(prepared)
    feature_frame = backtest.build_feature_frame(prepared, dd=4, section_baselines=section_baselines)

    excluded = feature_frame.loc[
        (feature_frame["section"] == "523-539") & (feature_frame["corner_bucket"] == "corner1")
    ]
    included = feature_frame.loc[
        (feature_frame["section"] == "501-522") & (feature_frame["corner_bucket"] == "corner1")
    ]
    assert not excluded.empty and not included.empty
    assert (excluded["h_nonjug_corner1_xdds"] == 0).all()
    assert (included["h_nonjug_corner1_xdds"] == 1).all()

    # dd24_boost も同様に 523-539 を外す（二重抑制ではなく、どちらも非付与）
    dd24_frame = backtest.build_feature_frame(prepared, dd=24, section_baselines=section_baselines)
    excluded_24 = dd24_frame.loc[(dd24_frame["section"] == "523-539") & (dd24_frame["corner_bucket"] == "corner1")]
    assert (excluded_24["dd24_boost"] == 0).all()
