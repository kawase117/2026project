#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
島別サブモデル訓練：Walk-forward検証
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from catboost import CatBoostClassifier
from sklearn.metrics import roc_auc_score, roc_curve
import json
import warnings

warnings.filterwarnings('ignore')

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"
DATA_CSV = Path(__file__).parent / "ml_data_island_submodel.csv"
OUTPUT_JSON = Path(__file__).parent / "ml_island_submodel_results.json"

# イベント日定義
EVENT_DAYS = {1, 4, 7, 14, 17, 24, 27, 30}

def load_data():
    """CSVからデータロード"""
    df = pd.read_csv(DATA_CSV)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    return df

def create_walk_forward_splits(df, train_months=12, test_months=1):
    """Walk-forward分割生成（月単位）"""
    min_date = df['date'].min()
    max_date = df['date'].max()

    splits = []
    current_train_start = min_date

    while current_train_start < max_date:
        train_end = current_train_start + pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=test_months)

        if test_end > max_date:
            test_end = max_date

        if test_start < max_date:
            splits.append({
                'train_start': current_train_start,
                'train_end': train_end,
                'test_start': test_start,
                'test_end': test_end
            })

        current_train_start = test_start

    return splits

def prepare_features(df):
    """特徴量準備"""
    features = ['dd', 'dow', 'is_event', 'games_normalized', 'diff_coins_normalized']

    # 機種タイプをカテゴリカル化（one-hot）
    machine_types = df['machine_type'].value_counts().head(10).index.tolist()
    for mt in machine_types:
        df[f'machine_type_{mt}'] = (df['machine_type'] == mt).astype(int)
        features.append(f'machine_type_{mt}')

    return features

def evaluate_predictions(y_true, y_pred_proba, y_pred_binary, k=10):
    """評価指標計算"""
    auc = roc_auc_score(y_true, y_pred_proba)

    # Hit@k: Top-k予測の中に実際の104%台がどの程度含まれるか
    n_top = min(k, len(y_true))
    top_indices = np.argsort(-y_pred_proba)[:n_top]
    hit_at_k = y_true[top_indices].sum() / max(y_true.sum(), 1)

    # ECE (Expected Calibration Error)
    bins = 10
    bin_edges = np.linspace(0, 1, bins + 1)
    ece = 0
    for i in range(bins):
        mask = (y_pred_proba >= bin_edges[i]) & (y_pred_proba < bin_edges[i+1])
        if mask.sum() > 0:
            bin_acc = y_true[mask].mean()
            bin_conf = y_pred_proba[mask].mean()
            ece += np.abs(bin_acc - bin_conf) * mask.sum() / len(y_true)

    return {'auc': auc, 'hit@k': hit_at_k, 'ece': ece}

def train_island_model(df_island, features, split, island_name):
    """島別モデル訓練"""
    train_mask = (df_island['date'] >= split['train_start']) & (df_island['date'] < split['train_end'])
    test_mask = (df_island['date'] >= split['test_start']) & (df_island['date'] < split['test_end'])

    df_train = df_island[train_mask]
    df_test = df_island[test_mask]

    if len(df_train) < 100 or len(df_test) < 10:
        return None

    X_train = df_train[features].fillna(0)
    y_train = df_train['target_104'].values
    X_test = df_test[features].fillna(0)
    y_test = df_test['target_104'].values

    model = CatBoostClassifier(
        iterations=100,
        depth=5,
        learning_rate=0.1,
        random_state=42,
        verbose=0,
        gpu_ram_part=0.5
    )

    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], early_stopping_rounds=10)

    y_pred_proba = model.predict_proba(X_test)[:, 1]
    y_pred_binary = model.predict(X_test)

    metrics = evaluate_predictions(y_test, y_pred_proba, y_pred_binary)

    return {
        'island': island_name,
        'train_start': split['train_start'].strftime('%Y-%m-%d'),
        'train_end': split['train_end'].strftime('%Y-%m-%d'),
        'test_start': split['test_start'].strftime('%Y-%m-%d'),
        'test_end': split['test_end'].strftime('%Y-%m-%d'),
        'train_size': len(df_train),
        'test_size': len(df_test),
        'test_104_rate': y_test.mean(),
        'auc': metrics['auc'],
        'hit@10': metrics['hit@k'],
        'ece': metrics['ece']
    }

print("=" * 80)
print("【島別サブモデル訓練：Walk-forward検証】")
print("=" * 80)

df = load_data()
features = prepare_features(df)
splits = create_walk_forward_splits(df)

results = []

for island in ['main_jug', 'main_mix', 'other']:
    print(f"\n【{island}】")
    df_island = df[df['island'] == island].copy()

    island_results = []
    for i, split in enumerate(splits):
        result = train_island_model(df_island, features, split, island)
        if result:
            island_results.append(result)
            print(f"  Split {i}: AUC={result['auc']:.4f}, Hit@10={result['hit@10']:.3f}, ECE={result['ece']:.4f}")

    # 島別集計
    if island_results:
        avg_auc = np.mean([r['auc'] for r in island_results])
        avg_hit = np.mean([r['hit@10'] for r in island_results])
        avg_ece = np.mean([r['ece'] for r in island_results])
        print(f"  平均: AUC={avg_auc:.4f}, Hit@10={avg_hit:.3f}, ECE={avg_ece:.4f}")

        results.extend(island_results)

print("\n" + "=" * 80)
print("【結果保存】")
print("=" * 80)

with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"保存: {OUTPUT_JSON}")
print(f"総Split数: {len(results)}")

# 全体集計
if results:
    print("\n【全体集計（島別平均）】")
    for island in ['main_jug', 'main_mix', 'other']:
        island_res = [r for r in results if r['island'] == island]
        if island_res:
            avg_auc = np.mean([r['auc'] for r in island_res])
            avg_hit = np.mean([r['hit@10'] for r in island_res])
            print(f"{island}: AUC={avg_auc:.4f}, Hit@10={avg_hit:.3f}")
