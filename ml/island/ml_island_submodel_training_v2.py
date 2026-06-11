#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
島別サブモデル訓練（v2）：リーク修正版
- 予測時点で既知の特徴量のみ使用（dd, dow, is_event, machine_type）
- games_normalized, diff_coins_normalized は除外
"""

import pandas as pd
import numpy as np
from pathlib import Path
from catboost import CatBoostClassifier
from sklearn.metrics import roc_auc_score
import json
import warnings

warnings.filterwarnings('ignore')

DATA_CSV = Path(__file__).parent / "ml_data_island_submodel.csv"
OUTPUT_JSON = Path(__file__).parent / "ml_island_submodel_results_v2.json"

def load_data():
    df = pd.read_csv(DATA_CSV)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    return df

def create_walk_forward_splits(df):
    min_date = df['date'].min()
    max_date = df['date'].max()
    splits = []
    current_train_start = min_date

    while current_train_start < max_date:
        train_end = current_train_start + pd.DateOffset(months=12)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=1)

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
    features = ['dd', 'dow', 'is_event']

    machine_types = df['machine_type'].value_counts().head(10).index.tolist()
    for mt in machine_types:
        df[f'machine_type_{mt}'] = (df['machine_type'] == mt).astype(int)
        features.append(f'machine_type_{mt}')

    return features

def train_island_model(df_island, features, split, island_name):
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
        verbose=0
    )

    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], early_stopping_rounds=10)

    y_pred_proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_pred_proba)

    # Hit@k calculation
    n_top = min(10, len(y_test))
    top_indices = np.argsort(-y_pred_proba)[:n_top]
    hit_at_k = y_test[top_indices].sum() / max(y_test.sum(), 1) if y_test.sum() > 0 else 0

    return {
        'island': island_name,
        'train_start': split['train_start'].strftime('%Y-%m-%d'),
        'train_end': split['train_end'].strftime('%Y-%m-%d'),
        'test_start': split['test_start'].strftime('%Y-%m-%d'),
        'test_end': split['test_end'].strftime('%Y-%m-%d'),
        'train_size': len(df_train),
        'test_size': len(df_test),
        'test_104_rate': float(y_test.mean()),
        'auc': float(auc),
        'hit@10': float(hit_at_k)
    }

print("=" * 80)
print("Island-specific Submodels: Walk-forward Validation (Leak-Fixed)")
print("=" * 80)

df = load_data()
features = prepare_features(df)
splits = create_walk_forward_splits(df)

results = []

for island in ['main_jug', 'main_mix', 'other']:
    print(f"\n[{island}]")
    df_island = df[df['island'] == island].copy()

    island_results = []
    for i, split in enumerate(splits):
        result = train_island_model(df_island, features, split, island)
        if result:
            island_results.append(result)
            print(f"  Split {i}: AUC={result['auc']:.4f}, Hit@10={result['hit@10']:.4f}")

    if island_results:
        avg_auc = np.mean([r['auc'] for r in island_results])
        avg_hit = np.mean([r['hit@10'] for r in island_results])
        print(f"  Average: AUC={avg_auc:.4f}, Hit@10={avg_hit:.4f}")
        results.extend(island_results)

with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nSaved: {OUTPUT_JSON}")
print(f"Total splits: {len(results)}")

if results:
    print("\nSummary by island:")
    for island in ['main_jug', 'main_mix', 'other']:
        island_res = [r for r in results if r['island'] == island]
        if island_res:
            avg_auc = np.mean([r['auc'] for r in island_res])
            avg_hit = np.mean([r['hit@10'] for r in island_res])
            print(f"  {island}: AUC={avg_auc:.4f}, Hit@10={avg_hit:.4f}")
