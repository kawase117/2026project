import sqlite3
import pandas as pd
import numpy as np
from typing import Tuple
from ml.feature_engineering import FeatureBuilder
from ml.utils.db_queries import load_daily_hall_with_date_info


def prepare_data_by_groupby(
    db_path: str,
    groupby_strategy: str,
    task: str,
    train_start: str = "2025-01-01",
    train_end: str = "2026-02-01",
    test_start: str = "2026-02-01",
    test_end: str = "2026-04-26",
    enable_extended_features: bool = False
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    グループ化戦略に応じてデータを準備し、訓練・テストセットを返す

    Args:
        db_path: SQLite DBファイルパス
        groupby_strategy: "tail" / "model_type" / "machine_number"
        task: "a" (勝率) / "b" (高利益確率)
        train_start, train_end, test_start, test_end: 日付（YYYY-MM-DD or YYYYMMDD）
        enable_extended_features: True の場合、FeatureBuilder を使用して22特徴量を生成
                                   False の場合（デフォルト），既存の3つの基本特徴量のみ

    Returns:
        (X_train, y_train, X_test, y_test)
        - enable_extended_features=False: X_train/X_test は groupby_strategy に応じた特徴量
        - enable_extended_features=True: X_train/X_test は 22次元の拡張特徴量
    """
    # DBから machine_detailed_results を読み込み
    conn = sqlite3.connect(db_path)
    query = """
        SELECT date, machine_number, machine_name, last_digit, is_zorome,
               games_normalized, diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    # 日付フォーマットを正規化
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    train_end_dt = pd.to_datetime(train_end)
    test_start_dt = pd.to_datetime(test_start)
    test_end_dt = pd.to_datetime(test_end)

    # 訓練・テストデータを分割
    train_mask = df["date"] <= train_end_dt
    test_mask = (df["date"] >= test_start_dt) & (df["date"] <= test_end_dt)

    df_train = df[train_mask].copy()
    df_test = df[test_mask].copy()

    # 拡張特徴量を使用する場合
    if enable_extended_features:
        # Hall データを読み込む（Task 2 の Hall-wide + Periodicity 特徴量用）
        df_train_hall, df_test_hall = load_daily_hall_with_date_info(
            db_path,
            train_start,
            train_end,
            test_start,
            test_end
        )

        # Create full dataframe (train + test) for proper rolling calculations
        df_full = pd.concat([df_train, df_test], ignore_index=True).sort_values('date')

        # FeatureBuilder で 53次元の拡張特徴量を生成
        fb_train = FeatureBuilder(
            df_train,
            df_hall=df_train_hall,
            df_full=df_full,
            train_end_date=train_end
        )
        X_train = fb_train.build_features(is_train=True, enable_extended_features=True)

        fb_test = FeatureBuilder(
            df_test,
            df_hall=df_test_hall,
            df_full=df_full,
            train_end_date=train_end
        )
        # Test時は訓練統計を使用（Data Leakage 防止）
        fb_test.train_stats = fb_train.train_stats
        X_test = fb_test.build_features(is_train=False, enable_extended_features=True)

        # ラベルを生成
        y_train = (df_train["diff_coins_normalized"] >= 1000).astype(int).values
        y_test = (df_test["diff_coins_normalized"] >= 1000).astype(int).values

        return X_train, y_train, X_test, y_test

    # グループ化戦略に応じて特徴量を生成（既存の3つの基本特徴量）
    if groupby_strategy == "tail":
        # 訓練セットのカラムをテストセットに適用
        tail_train = pd.get_dummies(df_train["last_digit"].astype(str), prefix="tail")
        tail_test = pd.get_dummies(df_test["last_digit"].astype(str), prefix="tail")
        # テストセットに訓練セットのカラムを合わせる
        tail_test = tail_test.reindex(columns=tail_train.columns, fill_value=0.0)
        X_train = tail_train.values.astype(float)
        X_test = tail_test.values.astype(float)
    elif groupby_strategy == "model_type":
        # 訓練セットのカラムをテストセットに適用
        model_train = pd.get_dummies(df_train["machine_name"], prefix="model")
        model_test = pd.get_dummies(df_test["machine_name"], prefix="model")
        # テストセットに訓練セットのカラムを合わせる
        model_test = model_test.reindex(columns=model_train.columns, fill_value=0.0)
        X_train = model_train.values.astype(float)
        X_test = model_test.values.astype(float)
    elif groupby_strategy == "machine_number":
        X_train = _create_features_machine_number(df_train)
        X_test = _create_features_machine_number(df_test)
    else:
        raise ValueError(f"Unknown groupby_strategy: {groupby_strategy}")

    # ラベルを生成（task a/b とも差枚 >= 1000）
    y_train = (df_train["diff_coins_normalized"] >= 1000).astype(int).values
    y_test = (df_test["diff_coins_normalized"] >= 1000).astype(int).values

    return X_train, y_train, X_test, y_test


def _create_features_tail(df: pd.DataFrame) -> np.ndarray:
    """末尾別グループ化による特徴量生成"""
    # one-hot encoding
    tail_dummies = pd.get_dummies(df["last_digit"].astype(str), prefix="tail")
    features = tail_dummies.values.astype(float)
    return features


def _create_features_model_type(df: pd.DataFrame) -> np.ndarray:
    """機種別グループ化による特徴量生成"""
    # one-hot encoding
    model_dummies = pd.get_dummies(df["machine_name"], prefix="model")
    features = model_dummies.values.astype(float)
    return features


def _create_features_machine_number(df: pd.DataFrame) -> np.ndarray:
    """台番号別グループ化による特徴量生成"""
    # 空DataFrameの処理
    if len(df) == 0:
        return np.array([]).reshape(0, 1)

    # 台番号を正規化（0～1範囲）
    machine_numbers = df["machine_number"].values.astype(float)
    machine_min = machine_numbers.min()
    machine_max = machine_numbers.max()
    if machine_max > machine_min:
        normalized = (machine_numbers - machine_min) / (machine_max - machine_min)
    else:
        normalized = np.zeros_like(machine_numbers)

    return normalized.reshape(-1, 1)
