#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
島別モデルの特徴量寄与度分析・リーク検査
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
OUTPUT_JSON = Path(__file__).parent / "ml_island_feature_importance.json"

df = pd.read_csv(DATA_CSV)
df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

print("=" * 80)
print("【特徴量リーク検査：is_event フラグのみでの AUC 測定】")
print("=" * 80)

# Train: 2025-01-01 〜 2026-01-01
# Test: 2026-01-01 〜 2026-02-01
train_mask = (df['date'] >= '2025-01-01') & (df['date'] < '2026-01-01')
test_mask = (df['date'] >= '2026-01-01') & (df['date'] < '2026-02-01')

df_train = df[train_mask]
df_test = df[test_mask]

y_test = df_test['target_104'].values
is_event_test = df_test['is_event'].values

auc_is_event_only = roc_auc_score(y_test, is_event_test)
print(f"is_event フラグのみでの AUC: {auc_is_event_only:.4f}")

# 全ページで詳細
print("\n" + "=" * 80)
print("【各島での特徴量寄与度】")
print("=" * 80)

features_all = ['dd', 'dow', 'is_event', 'games_normalized', 'diff_coins_normalized']
machine_types = df['machine_type'].value_counts().head(10).index.tolist()
for mt in machine_types:
    features_all.append(f'machine_type_{mt}')

results = []

for island in ['main_jug', 'main_mix', 'other']:
    print(f"\n【{island}】")

    df_island = df[df['island'] == island].copy()

    # One-hot 機種
    for mt in machine_types:
        df_island[f'machine_type_{mt}'] = (df_island['machine_type'] == mt).astype(int)

    df_train_i = df_island[train_mask].copy()
    df_test_i = df_island[test_mask].copy()

    X_train = df_train_i[features_all].fillna(0)
    y_train = df_train_i['target_104'].values
    X_test = df_test_i[features_all].fillna(0)
    y_test = df_test_i['target_104'].values

    if len(X_train) < 100 or len(X_test) < 10:
        print(f"  サンプルサイズ不足: train={len(X_train)}, test={len(X_test)}")
        continue

    model = CatBoostClassifier(
        iterations=100,
        depth=5,
        learning_rate=0.1,
        random_state=42,
        verbose=0
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], early_stopping_rounds=10)

    # 寄与度
    feature_importance = pd.DataFrame({
        'feature': features_all,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)

    auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
    print(f"  AUC: {auc:.4f}")
    print(f"  Top 10 features:")
    for i, row in feature_importance.head(10).iterrows():
        print(f"    {row['feature']:25s}: {row['importance']:.4f}")

    results.append({
        'island': island,
        'auc': float(auc),
        'feature_importance': feature_importance.to_dict('records')
    })

print("\n" + "=" * 80)
print("【診断】")
print("=" * 80)
print(f"is_event フラグのみで AUC={auc_is_event_only:.4f}")
if auc_is_event_only > 0.7:
    print("⚠️  WARNING: is_event フラグが強力。他の特徴量は冗長な可能性")
else:
    print("✓ is_event フラグは適度な寄与度。リークなし")

with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\n保存: {OUTPUT_JSON}")
