import pytest
import sqlite3
import tempfile
import pandas as pd
import numpy as np
from pathlib import Path
from ml.data_preparation import prepare_data_by_groupby


def test_prepare_data_tail_grouping():
    """末尾別グループ化でのデータ準備"""
    # テスト用DBを作成
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        # ダミーデータを作成
        test_data = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104"],
            "machine_number": [1, 2, 11, 12],
            "machine_name": ["機種A", "機種A", "機種A", "機種A"],
            "last_digit": ["1", "2", "1", "2"],
            "is_zorome": [0, 0, 0, 0],
            "games_normalized": [100, 100, 100, 100],
            "diff_coins_normalized": [1200, 800, 1500, -500]
        })
        test_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        # データ準備
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=str(db_path),
            groupby_strategy="tail",
            task="a",
            train_start="20250101",
            train_end="20250103",
            test_start="20250103",
            test_end="20250104"
        )

        # 訓練・テストデータのサイズを確認
        assert len(X_train) > 0
        assert len(X_test) > 0
        assert len(y_train) == len(X_train)
        assert len(y_test) == len(X_test)

        # ラベルが0または1であることを確認
        assert np.all((y_train == 0) | (y_train == 1))
        assert np.all((y_test == 0) | (y_test == 1))


def test_prepare_data_model_type_grouping():
    """機種別グループ化でのデータ準備"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        test_data = pd.DataFrame({
            "date": ["20250101", "20250102"],
            "machine_number": [1, 2],
            "machine_name": ["機種A", "機種B"],
            "last_digit": ["1", "2"],
            "is_zorome": [0, 0],
            "games_normalized": [100, 100],
            "diff_coins_normalized": [1200, 800]
        })
        test_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=str(db_path),
            groupby_strategy="model_type",
            task="a",
            train_start="20250101",
            train_end="20250101",
            test_start="20250102",
            test_end="20250102"
        )

        assert len(X_train) > 0
        assert len(X_test) > 0


def test_prepare_data_machine_number_grouping():
    """台番号別グループ化でのデータ準備"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        test_data = pd.DataFrame({
            "date": ["20250101", "20250102"],
            "machine_number": [1, 100],
            "machine_name": ["機種A", "機種A"],
            "last_digit": ["1", "0"],
            "is_zorome": [0, 0],
            "games_normalized": [100, 100],
            "diff_coins_normalized": [1200, -500]
        })
        test_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=str(db_path),
            groupby_strategy="machine_number",
            task="a",
            train_start="20250101",
            train_end="20250101",
            test_start="20250102",
            test_end="20250102"
        )

        assert len(X_train) > 0
        assert X_train.shape[1] == 1  # machine_number は 1 列


def test_prepare_data_invalid_groupby_strategy():
    """無効なグループ化戦略でのエラーハンドリング"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        test_data = pd.DataFrame({
            "date": ["20250101"],
            "machine_number": [1],
            "machine_name": ["機種A"],
            "last_digit": ["1"],
            "is_zorome": [0],
            "games_normalized": [100],
            "diff_coins_normalized": [1200]
        })
        test_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        with pytest.raises(ValueError):
            prepare_data_by_groupby(
                db_path=str(db_path),
                groupby_strategy="invalid_strategy",
                task="a"
            )


def test_prepare_data_empty_test_range():
    """テスト範囲にデータがない場合の処理"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        # 訓練範囲のみにデータを配置
        test_data = pd.DataFrame({
            "date": ["20250101", "20250102"],
            "machine_number": [1, 2],
            "machine_name": ["機種A", "機種A"],
            "last_digit": ["1", "2"],
            "is_zorome": [0, 0],
            "games_normalized": [100, 100],
            "diff_coins_normalized": [1200, 800]
        })
        test_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        # テスト範囲: 20250110-20250120 (データなし)
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=str(db_path),
            groupby_strategy="machine_number",
            task="a",
            train_start="20250101",
            train_end="20250102",
            test_start="20250110",
            test_end="20250120"
        )

        # 訓練セットは存在
        assert len(X_train) > 0
        assert len(y_train) > 0

        # テストセットは空
        assert len(X_test) == 0
        assert len(y_test) == 0

        # 空テストセットの shape は (0, 1)
        assert X_test.shape == (0, 1)


def test_prepare_data_with_extended_features():
    """拡張特徴量（22次元）でのデータ準備"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        # テスト用データを作成
        test_data = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104"],
            "machine_number": [1, 2, 11, 12],
            "machine_name": ["機種A", "機種A", "機種A", "機種A"],
            "last_digit": ["1", "2", "1", "2"],
            "is_zorome": [0, 0, 1, 0],
            "games_normalized": [100, 100, 100, 100],
            "diff_coins_normalized": [1200, 800, 1500, -500]
        })
        test_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        # 拡張特徴量を有効にしてデータ準備
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=str(db_path),
            groupby_strategy="tail",  # この値は無視される（enable_extended_features=True）
            task="a",
            train_start="20250101",
            train_end="20250103",
            test_start="20250103",
            test_end="20250104",
            enable_extended_features=True
        )

        # 特徴量の次元が 22 であることを確認
        assert X_train.shape[1] == 22, f"Expected 22 features, got {X_train.shape[1]}"
        assert X_test.shape[1] == 22, f"Expected 22 features, got {X_test.shape[1]}"

        # ラベルが正しく生成されていることを確認
        assert len(y_train) == len(X_train)
        assert len(y_test) == len(X_test)
        assert np.all((y_train == 0) | (y_train == 1))
        assert np.all((y_test == 0) | (y_test == 1))


def test_prepare_data_backward_compatibility():
    """enable_extended_features=False で既存の動作を保持（後方互換性）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        test_data = pd.DataFrame({
            "date": ["20250101", "20250102"],
            "machine_number": [1, 100],
            "machine_name": ["機種A", "機種A"],
            "last_digit": ["1", "0"],
            "is_zorome": [0, 0],
            "games_normalized": [100, 100],
            "diff_coins_normalized": [1200, -500]
        })
        test_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        # enable_extended_features=False（デフォルト）で従来の動作を確認
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=str(db_path),
            groupby_strategy="machine_number",
            task="a",
            train_start="20250101",
            train_end="20250101",
            test_start="20250102",
            test_end="20250102",
            enable_extended_features=False  # デフォルト値
        )

        # 機械学習モデル用の1次元特徴量
        assert X_train.shape[1] == 1
        assert X_test.shape[1] == 1
