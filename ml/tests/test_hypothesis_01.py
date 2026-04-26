import pytest
import tempfile
import json
from pathlib import Path
from ml.hypothesis_01_groupby import run_hypothesis_1_experiments


def test_hypothesis_1_execution():
    """仮説1（グループ化戦略検証）の実行"""
    import sqlite3
    import pandas as pd

    with tempfile.TemporaryDirectory() as tmpdir:
        # テスト用DBを作成
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        # テスト用ダミーデータ：訓練期間（2025-01-01～2026-02-01）とテスト期間（2026-02-01～2026-04-26）の両方を含める
        # 訓練期間：30日分
        train_dates = pd.date_range("2025-01-01", periods=30, freq="D")
        train_data = pd.DataFrame({
            "date": train_dates.strftime("%Y%m%d").tolist() * 2,
            "machine_number": [1] * 30 + [2] * 30,
            "machine_name": ["機種A"] * 30 + ["機種B"] * 30,
            "last_digit": ["1"] * 30 + ["2"] * 30,
            "is_zorome": [0] * 60,
            "games_normalized": [100] * 60,
            "diff_coins_normalized": [1200, -500] * 30
        })

        # テスト期間：30日分（2026-02-01～2026-03-01）
        test_dates = pd.date_range("2026-02-01", periods=30, freq="D")
        test_data_df = pd.DataFrame({
            "date": test_dates.strftime("%Y%m%d").tolist() * 2,
            "machine_number": [1] * 30 + [2] * 30,
            "machine_name": ["機種A"] * 30 + ["機種B"] * 30,
            "last_digit": ["1"] * 30 + ["2"] * 30,
            "is_zorome": [0] * 60,
            "games_normalized": [100] * 60,
            "diff_coins_normalized": [1200, -500] * 30
        })

        # 訓練とテストデータを結合
        all_data = pd.concat([train_data, test_data_df], ignore_index=True)
        all_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        # テスト用の出力ディレクトリ
        results_dir = Path(tmpdir) / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        # 仮説1を実行
        run_hypothesis_1_experiments(db_path=str(db_path), results_dir=str(results_dir))

        # 6つの実験ログが生成されたかを確認
        exp_files = list(results_dir.glob("exp_001_groupby_*.json"))
        assert len(exp_files) == 6, f"Expected 6 experiment logs, got {len(exp_files)}"

        # 各ログファイルの内容を検証
        for exp_file in exp_files:
            with open(exp_file, "r", encoding="utf-8") as f:
                exp_log = json.load(f)

            # ログの必須キーを確認
            assert "experiment_id" in exp_log
            assert "phase" in exp_log
            assert exp_log["phase"] == 1
            assert "hypothesis" in exp_log
            assert "groupby_strategy" in exp_log
            assert exp_log["groupby_strategy"] in ["tail", "model_type", "machine_number"]
            assert "task" in exp_log
            assert exp_log["task"] in ["a", "b"]
            assert "ml_model" in exp_log
            assert exp_log["ml_model"] == "logistic"
            assert "metrics" in exp_log
            assert "auc" in exp_log["metrics"]
            assert "accuracy" in exp_log["metrics"]


def test_hypothesis_1_imports():
    """必要なモジュールがインポートできるか確認"""
    from ml.hypothesis_01_groupby import run_hypothesis_1_experiments
    assert callable(run_hypothesis_1_experiments)
